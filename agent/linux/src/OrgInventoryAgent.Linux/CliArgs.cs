namespace OrgInventoryAgent.Linux;

/// <summary>Parse CLI args đơn giản (--key value / --flag).</summary>
internal sealed class CliArgs
{
    public string? DataDir { get; private set; }
    public string? ConfigPath { get; private set; }
    public string? EnrollToken { get; private set; }
    public string? Endpoint { get; private set; }
    public int? InventorySeconds { get; private set; }
    public bool PrintConfig { get; private set; }
    public bool PrintFingerprint { get; private set; }
    public bool PrintInventory { get; private set; }
    public bool PrintSecurity { get; private set; }
    public bool PrintAbout { get; private set; }
    public bool PrintVersion { get; private set; }
    public bool Once { get; private set; }
    public bool SendInventory { get; private set; }
    public bool ShowHelp { get; private set; }

    public static CliArgs Parse(string[] args)
    {
        var cli = new CliArgs();
        for (int i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            string? Next() => i + 1 < args.Length ? args[++i] : null;
            switch (arg)
            {
                case "--data-dir": cli.DataDir = Next(); break;
                case "--config": cli.ConfigPath = Next(); break;
                case "--enroll-token": cli.EnrollToken = Next(); break;
                case "--endpoint": cli.Endpoint = Next(); break;
                case "--inventory-seconds":
                case "--inventory-interval":
                    if (int.TryParse(Next(), out var sec)) cli.InventorySeconds = sec;
                    break;
                case "--print-config": cli.PrintConfig = true; break;
                case "--print-fingerprint": cli.PrintFingerprint = true; break;
                case "--print-inventory": cli.PrintInventory = true; break;
                case "--print-security": cli.PrintSecurity = true; break;
                case "--about":
                case "--info": cli.PrintAbout = true; break;
                case "--version":
                case "-v": cli.PrintVersion = true; break;
                case "--once": cli.Once = true; break;
                case "--send-inventory": cli.SendInventory = true; break;
                case "--help":
                case "-h": cli.ShowHelp = true; break;
                default:
                    Console.Error.WriteLine($"[warn] Bỏ qua tham số không biết: {arg}");
                    break;
            }
        }
        return cli;
    }
}