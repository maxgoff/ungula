"""
Agent runner for processing chat messages.

The AgentRunner is stateless - it assembles context per-request from
workspace files and conversation history, then queries the LLM.

Uses a tool calling loop to let the LLM autonomously decide when
to use tools (web search, shell, etc.) and iteratively refine
responses based on tool results.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import UUID

from ..llm.base import (
    CompletionRequest,
    CompletionResponse,
    Message as LLMMessage,
    MessageRole,
    StreamChunk,
    ToolCall,
)
from ..llm.registry import ProviderRegistry
from ..skills.loader import SkillRegistry
from ..storage.base import MessageCreate, StorageBackend
from ..tools.base import ToolRegistry, ToolResult
from ..tools.policy import PolicyEngine, ToolPolicy
from .compaction import CompactionConfig, compact_if_needed
from .context import SystemPromptBuilder
from .context_pruning import PruningConfig, prune_tool_results
from .intent import IntentClassifier, IntentType

logger = logging.getLogger(__name__)


@dataclass
class AgentRunner:
    """
    Stateless agent runtime.

    Assembles context from workspace files and conversation history,
    queries the LLM via registry with tool calling support, and
    persists responses.
    """

    storage: StorageBackend
    registry: ProviderRegistry
    workspace_dir: Path

    # Configuration
    default_provider: str | None = None
    default_model: str | None = None
    max_history_messages: int = 50
    default_temperature: float = 0.7
    default_max_tokens: int | None = None

    # Tools and Skills
    tool_registry: ToolRegistry | None = None
    skill_registry: SkillRegistry | None = None
    policy_engine: PolicyEngine | None = None
    max_tool_iterations: int = 10

    # Context management
    compaction_config: CompactionConfig | None = None
    pruning_config: PruningConfig | None = None

    async def run(
        self,
        conversation_id: UUID,
        user_message: str,
        *,
        stream: bool = False,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        session_type: str | None = None,
        provider_params: dict[str, Any] | None = None,
    ) -> CompletionResponse | AsyncIterator[StreamChunk]:
        """
        Execute an agent turn.

        Args:
            conversation_id: The conversation to continue.
            user_message: User's input message.
            stream: Whether to stream the response.
            provider: Override default provider.
            model: Override default model.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.

        Returns:
            CompletionResponse for non-streaming,
            AsyncIterator[StreamChunk] for streaming.
        """
        # 1. Persist user message
        await self.storage.create_message(
            MessageCreate(
                conversation_id=conversation_id,
                role="user",
                content=user_message,
            )
        )

        # 2. Check if we're in a clarification context
        skip_intent = await self._is_post_clarification(conversation_id)
        if skip_intent:
            logger.info("Post-clarification context detected, skipping intent classification")

        if not skip_intent:
            # 3. Classify intent (only for short-circuit paths)
            intent = await self._classify_intent(user_message)
            logger.info(
                "Intent: %s (confidence: %.2f) - %s",
                intent.primary_intent.value,
                intent.confidence,
                intent.reasoning or "no reasoning",
            )

            # 4. Short-circuit: CLARIFICATION_NEEDED
            if intent.primary_intent == IntentType.CLARIFICATION_NEEDED:
                response_content = self._build_clarification_response(intent)
                await self.storage.create_message(
                    MessageCreate(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=response_content,
                        metadata={"intent": "clarification", "interpretations": intent.interpretations},
                    )
                )
                response = CompletionResponse(
                    content=response_content,
                    model="system",
                    provider="ungula",
                )
                if stream:
                    return self._response_to_stream(response)
                return response

        if not skip_intent and intent.primary_intent == IntentType.SYSTEM_INQUIRY:
            # Short-circuit: SYSTEM_INQUIRY
            response_content = await self._get_system_capabilities_response()
            await self.storage.create_message(
                MessageCreate(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=response_content,
                    metadata={"intent": "system_inquiry"},
                )
            )
            response = CompletionResponse(
                content=response_content,
                model="system",
                provider="ungula",
            )
            if stream:
                return self._response_to_stream(response)
            return response

        # 5. Build system prompt (workspace files + skills prompt)
        skills_prompt = self.skill_registry.build_skills_prompt() if self.skill_registry else None
        prompt_builder = SystemPromptBuilder(
            self.workspace_dir,
            skills_prompt=skills_prompt,
            session_type=session_type,
        )
        try:
            system_prompt = prompt_builder.build()
        except FileNotFoundError as e:
            logger.warning("Workspace file missing, using minimal prompt: %s", e)
            system_prompt = "You are a helpful AI assistant."

        # 6. Load history (with potential compaction)
        history_result = await self._get_history(conversation_id, system_prompt)
        compaction_summary = None
        if isinstance(history_result, tuple):
            history, compaction_summary = history_result
        else:
            history = history_result

        messages = self._build_messages(system_prompt, history, user_message, compaction_summary)

        # 7. Execute via tool calling loop
        effective_provider = provider or self.default_provider

        if stream:
            return self._stream_with_tool_loop(
                messages,
                conversation_id,
                provider=effective_provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                provider_params=provider_params,
            )
        else:
            return await self._complete_with_tool_loop(
                messages,
                conversation_id,
                provider=effective_provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                provider_params=provider_params,
            )

    # --- Tool Calling Loop ---

    def _get_filtered_tool_definitions(self) -> list:
        """Get tool definitions filtered through the policy engine."""
        if not self.tool_registry:
            return []
        tools = self.tool_registry.get_all()
        if self.policy_engine:
            tools = self.policy_engine.filter_tools(tools)
        # Build definitions from filtered tools
        from ..llm.base import ToolDefinition
        return [
            ToolDefinition(
                name=t.get_schema()["function"]["name"],
                description=t.get_schema()["function"]["description"],
                parameters=t.get_schema()["function"]["parameters"],
            )
            for t in tools
        ]

    async def _run_tool_loop(
        self,
        messages: list[LLMMessage],
        *,
        provider: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        provider_params: dict[str, Any] | None = None,
    ) -> tuple[CompletionResponse, list[dict]]:
        """Execute the non-streaming tool calling loop.

        Returns:
            Tuple of (final_response, tool_call_log).
        """
        tool_definitions = self._get_filtered_tool_definitions()
        tool_call_log: list[dict] = []

        for iteration in range(self.max_tool_iterations):
            logger.info("Tool loop iteration %d/%d", iteration + 1, self.max_tool_iterations)

            request = CompletionRequest(
                messages=list(messages),
                model=model or self.default_model,
                temperature=temperature or self.default_temperature,
                max_tokens=max_tokens or self.default_max_tokens,
                tools=tool_definitions if tool_definitions else None,
                stream=False,
                provider_params=provider_params or {},
            )

            response = await self.registry.complete(request, provider=provider)

            if not response.has_tool_calls:
                return response, tool_call_log

            # Append assistant message with tool calls
            messages.append(LLMMessage(
                role=MessageRole.ASSISTANT,
                content=response.content or "",
                tool_calls=[tc.to_dict() for tc in response.tool_calls],
            ))

            # Execute each tool call
            for tc in response.tool_calls:
                result, log_entry = await self._execute_tool_call(tc, iteration + 1)
                tool_call_log.append(log_entry)

                messages.append(LLMMessage(
                    role=MessageRole.TOOL,
                    content=result.to_message(),
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        # Max iterations reached -- force a text response
        logger.warning(
            "Tool loop reached max iterations (%d), forcing text response",
            self.max_tool_iterations,
        )
        request = CompletionRequest(
            messages=list(messages),
            model=model or self.default_model,
            temperature=temperature or self.default_temperature,
            max_tokens=max_tokens or self.default_max_tokens,
            tools=None,  # No tools forces text response
            stream=False,
            provider_params=provider_params or {},
        )
        response = await self.registry.complete(request, provider=provider)
        return response, tool_call_log

    async def _stream_tool_loop(
        self,
        messages: list[LLMMessage],
        *,
        provider: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        provider_params: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Execute the streaming tool calling loop.

        Streams text content. When tool calls are detected, emits
        tool_call/tool_result SSE events with timing info, then starts
        a new stream.
        """
        tool_definitions = self._get_filtered_tool_definitions()

        for iteration in range(self.max_tool_iterations):
            logger.info("Stream tool loop iteration %d/%d", iteration + 1, self.max_tool_iterations)

            is_last = iteration == self.max_tool_iterations - 1

            request = CompletionRequest(
                messages=list(messages),
                model=model or self.default_model,
                temperature=temperature or self.default_temperature,
                max_tokens=max_tokens or self.default_max_tokens,
                tools=tool_definitions if (tool_definitions and not is_last) else None,
                stream=True,
                provider_params=provider_params or {},
            )

            accumulated_content = ""
            accumulated_tool_calls: list[ToolCall] = []
            final_model = model

            async for chunk in self.registry.stream(request, provider=provider):
                if chunk.content:
                    accumulated_content += chunk.content
                    yield chunk

                if chunk.model:
                    final_model = chunk.model

                if chunk.tool_calls:
                    accumulated_tool_calls.extend(chunk.tool_calls)

                # If done with no tool calls, we're finished
                if chunk.is_done and not accumulated_tool_calls:
                    yield chunk
                    return

            # If no tool calls accumulated, done
            if not accumulated_tool_calls:
                return

            # We have tool calls -- execute them
            messages.append(LLMMessage(
                role=MessageRole.ASSISTANT,
                content=accumulated_content or "",
                tool_calls=[tc.to_dict() for tc in accumulated_tool_calls],
            ))

            for tc in accumulated_tool_calls:
                # Truncate arguments for the event data
                try:
                    args_preview = tc.arguments[:500] if tc.arguments else ""
                except Exception:
                    args_preview = ""

                # Emit tool_call event with arguments
                yield StreamChunk(
                    event_type="tool_call",
                    event_data={
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "arguments": args_preview,
                    },
                )

                # Execute with timing
                t0 = time.monotonic()
                result, _ = await self._execute_tool_call(tc, iteration + 1)
                execution_time_ms = int((time.monotonic() - t0) * 1000)

                # Emit tool_result event with timing and expanded preview
                yield StreamChunk(
                    event_type="tool_result",
                    event_data={
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "success": result.success,
                        "output_preview": result.output[:500] if result.output else "",
                        "error": result.error,
                        "execution_time_ms": execution_time_ms,
                    },
                )

                messages.append(LLMMessage(
                    role=MessageRole.TOOL,
                    content=result.to_message(),
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

            # Loop continues with next streaming iteration

        # Max iterations
        logger.warning("Stream tool loop reached max iterations (%d)", self.max_tool_iterations)
        yield StreamChunk(finish_reason="max_iterations", model=final_model)

    async def _execute_tool_call(
        self, tc: ToolCall, iteration: int
    ) -> tuple[ToolResult, dict]:
        """Execute a single tool call and return result + log entry."""
        try:
            arguments = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError:
            arguments = {}
            result = ToolResult(
                success=False,
                output="",
                error=f"Invalid JSON arguments: {tc.arguments[:200]}",
            )
            log_entry = {
                "iteration": iteration,
                "tool_call_id": tc.id,
                "name": tc.name,
                "arguments": {},
                "success": False,
                "error": "Invalid JSON arguments",
            }
            return result, log_entry

        logger.info("Executing tool: %s(%s)", tc.name, str(arguments)[:100])

        if self.tool_registry:
            result = await self.tool_registry.execute(tc.name, **arguments)
        else:
            result = ToolResult(success=False, output="", error="No tool registry available")

        logger.info("Tool %s result: success=%s, output_len=%d", tc.name, result.success, len(result.output))

        log_entry = {
            "iteration": iteration,
            "tool_call_id": tc.id,
            "name": tc.name,
            "arguments": arguments,
            "success": result.success,
            "output_preview": result.output[:200] if result.output else None,
            "error": result.error,
        }
        return result, log_entry

    # --- Persistence Wrappers ---

    async def _complete_with_tool_loop(
        self,
        messages: list[LLMMessage],
        conversation_id: UUID,
        *,
        provider: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        provider_params: dict[str, Any] | None = None,
    ) -> CompletionResponse:
        """Execute tool loop and persist final result."""
        response, tool_call_log = await self._run_tool_loop(
            messages,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_params=provider_params,
        )

        # Record token usage
        await self._record_usage(response, conversation_id)

        metadata: dict = {"provider": response.provider}
        if tool_call_log:
            metadata["tool_calls"] = tool_call_log
            metadata["tool_iterations"] = tool_call_log[-1]["iteration"] if tool_call_log else 0

        await self.storage.create_message(
            MessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                content=response.content or "",
                model=response.model,
                metadata=metadata,
            )
        )

        return response

    async def _stream_with_tool_loop(
        self,
        messages: list[LLMMessage],
        conversation_id: UUID,
        *,
        provider: str | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        provider_params: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream tool loop with persistence."""
        accumulated_content = ""
        final_model = None

        async for chunk in self._stream_tool_loop(
            messages,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_params=provider_params,
        ):
            if chunk.content:
                accumulated_content += chunk.content
            if chunk.model:
                final_model = chunk.model

            yield chunk

            if chunk.is_done:
                await self.storage.create_message(
                    MessageCreate(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=accumulated_content,
                        model=final_model,
                        metadata={"provider": provider or "unknown"},
                    )
                )

    # --- Token Usage Recording ---

    async def _record_usage(
        self,
        response: CompletionResponse,
        conversation_id: UUID | None = None,
    ) -> None:
        """Record token usage from an LLM response."""
        if not response.usage:
            return
        try:
            from ..storage.base import TokenUsageCreate

            await self.storage.record_token_usage(
                TokenUsageCreate(
                    conversation_id=conversation_id,
                    provider=response.provider,
                    model=response.model,
                    prompt_tokens=response.usage.get("prompt_tokens", 0),
                    completion_tokens=response.usage.get("completion_tokens", 0),
                    total_tokens=response.usage.get("total_tokens", 0),
                )
            )
        except Exception as e:
            logger.warning("Failed to record token usage: %s", e)

    # --- Helper Methods ---

    async def _is_post_clarification(self, conversation_id: UUID) -> bool:
        """Check if the previous assistant message was a clarification request."""
        history = await self.storage.list_messages(conversation_id, limit=3)
        for msg in reversed(history):
            if msg.role == "assistant":
                metadata = msg.metadata or {}
                return metadata.get("intent") in ("clarification", "clarification_followup")
        return False

    async def _get_history(
        self,
        conversation_id: UUID,
        system_prompt: str = "",
    ) -> list | tuple[list, str]:
        """Load conversation history, compacting if needed.

        Returns either:
            - A list of messages (no compaction needed), or
            - A tuple of (recent_messages, summary) if compaction occurred.
        """
        messages = await self.storage.list_messages(
            conversation_id,
            limit=self.max_history_messages,
        )

        # Attempt compaction
        result = await compact_if_needed(
            messages,
            system_prompt,
            registry=self.registry,
            storage=self.storage,
            conversation_id=conversation_id,
            provider=self.default_provider,
            config=self.compaction_config,
        )

        return result

    def _build_messages(
        self,
        system_prompt: str,
        history: list,
        current_user_message: str | None = None,
        compaction_summary: str | None = None,
    ) -> list[LLMMessage]:
        """Assemble messages list for LLM, with optional tool result pruning."""
        messages = [
            LLMMessage(role=MessageRole.SYSTEM, content=system_prompt)
        ]

        # Insert compaction summary before history if present
        if compaction_summary:
            messages.append(LLMMessage(
                role=MessageRole.SYSTEM,
                content=f"[Summary of earlier conversation]\n{compaction_summary}",
            ))

        for msg in history:
            if msg.role in ("user", "assistant"):
                messages.append(
                    LLMMessage(
                        role=MessageRole(msg.role),
                        content=msg.content,
                    )
                )

        if current_user_message:
            messages.append(LLMMessage(role=MessageRole.USER, content=current_user_message))

        # Apply tool result pruning to reduce context pressure
        pruning_cfg = self.pruning_config or PruningConfig()
        if pruning_cfg.enabled:
            from .token_counter import estimate_tokens
            system_tokens = estimate_tokens(system_prompt)
            max_ctx = (self.compaction_config or CompactionConfig()).max_context_tokens
            prune_tool_results(messages, system_tokens, max_ctx, pruning_cfg)

        return messages

    async def _classify_intent(self, user_message: str) -> "IntentClassification":
        """Classify the user's intent using an LLM."""
        from .intent import IntentClassification, IntentClassifier

        classifier = IntentClassifier(
            llm_registry=self.registry,
            tool_registry=self.tool_registry,
            provider=self.default_provider,
        )
        return await classifier.classify(user_message)

    def _build_clarification_response(self, intent: "IntentClassification") -> str:
        """Build a response asking for clarification."""
        lines = ["I want to make sure I understand what you're asking.\n"]

        if intent.interpretations:
            lines.append("Your question could mean:\n")
            for i, interp in enumerate(intent.interpretations, 1):
                meaning = interp.get("meaning", "Unknown")
                prob = interp.get("probability", 0)
                lines.append(f"{i}. {meaning} (likelihood: {prob:.0%})")
            lines.append("")

        if intent.clarification_question:
            lines.append(intent.clarification_question)
        else:
            lines.append("Could you please clarify what you mean?")

        return "\n".join(lines)

    async def _get_system_capabilities_response(self) -> str:
        """Generate a response describing Ungula's actual capabilities."""
        lines = [
            "# Ungula System Capabilities\n",
            "I'm Ungula, an AI agent platform. Here's what I can actually do:\n",
            "## Registered LLM Providers & Models",
        ]

        providers = self.registry.list_providers()
        if providers:
            all_models = await self.registry.list_models()
            for provider_name in providers:
                provider = self.registry.get(provider_name)
                display = provider.display_name if provider else provider_name
                models = all_models.get(provider_name, [])
                lines.append(f"\n### {display}")
                if models:
                    for model in models:
                        marker = " *(default)*" if provider and model == provider.default_model else ""
                        lines.append(f"- `{model}`{marker}")
                else:
                    lines.append(f"- Default model: `{provider.default_model}`" if provider else "- No models listed")
        else:
            lines.append("- No LLM providers currently registered")

        lines.append("")
        lines.append("## Registered Tools")

        if self.tool_registry:
            tools = self.tool_registry.get_all()
            if tools:
                for tool in tools:
                    lines.append(f"- **{tool.name}**: {tool.description}")
            else:
                lines.append("- No tools currently registered")
        else:
            lines.append("- No tools currently registered")

        # Skills section
        if self.skill_registry:
            eligible = self.skill_registry.list_eligible()
            if eligible:
                lines.append("")
                lines.append("## Active Skills")
                for skill in eligible:
                    emoji = skill.metadata.emoji or ""
                    lines.append(f"- {emoji} **{skill.metadata.name}**: {skill.metadata.description}")

        lines.extend([
            "",
            "## Core Capabilities",
            "- **Tool Calling**: I can autonomously use tools to answer your questions",
            "- **Web Search**: I can search the web for real-time information",
            "- **Conversation**: I can have contextual conversations with memory",
            "- **Multi-Channel**: I can communicate via Telegram, Discord, and API",
            "- **Skills**: I can be extended with new capabilities via the skills framework",
            "",
            "Is there something specific you'd like me to help with?",
        ])

        return "\n".join(lines)

    async def _response_to_stream(
        self, response: CompletionResponse
    ) -> AsyncIterator[StreamChunk]:
        """Wrap a CompletionResponse as a single-chunk stream."""
        yield StreamChunk(
            content=response.content,
            model=response.model,
            finish_reason=response.finish_reason or "stop",
        )
