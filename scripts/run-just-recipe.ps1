param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string] $Recipe
)

trap [System.Management.Automation.PipelineStoppedException] {
  [Console]::Error.WriteLine("Interrupted.")
  exit 130
}

& ([scriptblock]::Create($Recipe))

if ($null -ne $LASTEXITCODE) {
  exit $LASTEXITCODE
}
