import { Link, useLocation } from "react-router-dom";

const links = [
  { to: "/purge", label: "Purge" },
  { to: "/users", label: "Users" },
  { to: "/history", label: "History" },
];

export default function Navbar() {
  const { pathname } = useLocation();
  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-white text-lg">M365 Purger</span>
      {links.map(l => (
        <Link key={l.to} to={l.to}
          className={`text-sm ${pathname.startsWith(l.to) ? "text-white font-semibold" : "text-gray-400 hover:text-white"}`}>
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
