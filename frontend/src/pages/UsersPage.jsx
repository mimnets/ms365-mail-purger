import { useEffect, useState } from "react";
import { listUsers } from "../api/client";

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listUsers()
      .then(res => setUsers(res.data.users || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = users.filter(u =>
    u.displayName?.toLowerCase().includes(search.toLowerCase()) ||
    u.mail?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Mailboxes</h2>
      <input
        className="mb-4 w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
        placeholder="Search users..."
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      {loading && <p className="text-gray-400">Loading...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}
      {!loading && !error && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-700">
              <th className="pb-2">Name</th>
              <th className="pb-2">Email</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(u => (
              <tr key={u.id} className="border-b border-gray-800 hover:bg-gray-800">
                <td className="py-2">{u.displayName}</td>
                <td className="py-2 text-blue-400">{u.mail || u.userPrincipalName}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
