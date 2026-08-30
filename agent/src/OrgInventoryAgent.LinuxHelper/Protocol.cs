namespace OrgInventoryAgent.LinuxHelper;

public sealed class HelperRequest
{
    public string Operation { get; set; } = "";   // smartctl | dmi | luks
    public Dictionary<string, string>? Args { get; set; }
}

public sealed class HelperResponse
{
    public bool Ok { get; set; }
    public object? Data { get; set; }
    public string? Error { get; set; }
}