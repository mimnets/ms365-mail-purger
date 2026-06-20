export default function SetupGuidePage() {
  const steps = [
    {
      title: "Step 1: Create App Registration in Azure",
      content: [
        "Go to portal.azure.com → Azure Active Directory → App Registrations → New Registration",
        "Name: M365 Mail Purger",
        "Supported account types: Accounts in this organizational directory only",
        "Redirect URI: (leave blank — this app uses certificate auth, not interactive login)",
        "Click Register",
        "Copy the Application (client) ID and Directory (tenant) ID",
        "Enter them in Settings → Add Organization",
      ],
    },
    {
      title: "Step 2: Generate Certificate & Upload to Azure",
      content: [
        "In this app, go to Settings → click 'Generate Certificate' for your org",
        "This downloads a .cer file (public key certificate)",
        "In Azure portal, go to your app → Certificates & secrets → Certificates → Upload certificate",
        "Upload the downloaded .cer file",
        "Copy the Thumbprint shown in Azure and note it down",
      ],
    },
    {
      title: "Step 3: Grant API Permissions (Application Permissions)",
      content: [
        "In Azure portal, go to your app → API Permissions → Add a permission",
        "Choose Microsoft Graph → Application permissions",
        "Add ALL of these:",
        "  • Mail.ReadWrite",
        "  • Mail.ReadWrite.Shared",
        "  • User.Read.All",
        "  • MailboxSettings.Read",
        "  • Reports.Read.All",
        "Click 'Grant admin consent for [your tenant]'",
        "All permissions must show a green checkmark",
      ],
    },
    {
      title: "Step 4: Assign eDiscovery Manager Role",
      content: [
        "Go to Microsoft Purview compliance portal (compliance.microsoft.com)",
        "Go to Permissions → eDiscovery Manager",
        "Add the app (service principal) as an eDiscovery Manager",
        "Alternatively: Add the admin user (e.g. monir.it@vclbd.net) as eDiscovery Manager",
        "This is REQUIRED for compliance search and purge actions to work",
        "",
        "Note: If you cannot access Purview portal, have a Global Admin do this step.",
      ],
    },
    {
      title: "Step 5: Connect.IPPSSession Authentication Flow",
      content: [
        "This app uses PowerShell Core (pwsh) on Linux to run:",
        "  Connect-IPPSSession -AppId <ID> -CertificateFilePath <cert> -CertificatePassword <pass> -Organization <domain> -TenantId <id>",
        "",
        "The certificate (.pfx) is stored encrypted in the database.",
        "Every purge job decrypts the cert, writes a temp file, runs pwsh, then cleans up.",
        "",
        "Date range is split into weekly chunks.",
        "Each week: Create ComplianceSearch → Start → Wait → Purge (max 10 items per action)",
        "Powershell outputs progress lines which the Python backend reads live.",
      ],
    },
    {
      title: "Step 6: Start Purging",
      content: [
        "Go to the Purge tab",
        "Select your organization from the dropdown",
        "Select a user mailbox you want to clean up",
        "Pick a date range (start small — test with 1 week first)",
        "Click Preview Count to estimate emails",
        "Click Start Purge to begin",
        "Watch the live dashboard as progress updates every 3 seconds",
      ],
    },
  ];

  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-bold mb-2">Setup Guide</h2>
      <p className="text-gray-400 mb-6">
        Step-by-step instructions to configure Azure AD and start using the mail purger.
      </p>

      <div className="space-y-6">
        {steps.map((step, i) => (
          <div key={i} className="bg-gray-800 rounded-lg p-5 border border-gray-700">
            <h3 className="text-lg font-semibold text-white mb-3">{step.title}</h3>
            <ul className="space-y-2">
              {step.content.map((line, j) => (
                <li key={j} className={`text-sm ${line.startsWith("  •") ? "text-blue-400 pl-4" : line.startsWith("  ") ? "text-gray-400 pl-4 font-mono text-xs" : line === "" ? "" : "text-gray-300"}`}>
                  {line || <br />}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4 mt-6">
        <h3 className="font-semibold text-yellow-300 mb-2">⚠ Important Notes</h3>
        <ul className="text-sm text-yellow-200 space-y-1">
          <li>• Compliance searches can take 1-5 minutes to complete per week chunk</li>
          <li>• Each purge action deletes max 10 items — many actions may be needed for large mailboxes</li>
          <li>• This performs soft delete (moves to Recoverable Items for 14-30 days)</li>
          <li>• In-place archive IS covered — compliance search scans both primary + archive</li>
          <li>• The eDiscovery Manager role is MANDATORY for purge to work</li>
          <li>• Test with a small date range first before doing a full mailbox</li>
        </ul>
      </div>
    </div>
  );
}
