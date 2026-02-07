import Sidebar from './Sidebar';

export default function Layout({ children }) {
  return (
    <div className="h-screen bg-gray-900 text-gray-100 flex">
      <Sidebar />
      <main className="flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
