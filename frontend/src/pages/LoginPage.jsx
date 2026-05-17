import { authLogin } from "../api/client";

export default function LoginPage() {
  const handleLogin = async () => {
    try {
      const res = await authLogin();
      window.location.href = res.data.auth_url;
    } catch (e) {
      alert("Login failed: " + e.message);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] gap-6">
      <h1 className="text-3xl font-bold text-white">M365 Mail Purger</h1>
      <p className="text-gray-400">Sign in with your Microsoft admin account</p>
      <button
        onClick={handleLogin}
        className="flex items-center gap-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-3 rounded-lg transition"
      >
        Sign in with Microsoft
      </button>
    </div>
  );
}
