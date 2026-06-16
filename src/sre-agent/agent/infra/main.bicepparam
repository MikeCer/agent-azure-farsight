using './main.bicep'

param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'agent-azure-farsight-sre')
param location = readEnvironmentVariable('AZURE_LOCATION', 'westeurope')
param principalId = readEnvironmentVariable('AZURE_PRINCIPAL_ID', '')
param upgradeChannel = readEnvironmentVariable('SRE_AGENT_UPGRADE_CHANNEL', 'Stable')
param defaultModelProvider = readEnvironmentVariable('SRE_AGENT_DEFAULT_MODEL_PROVIDER', 'Anthropic')
param defaultModelName = readEnvironmentVariable('SRE_AGENT_DEFAULT_MODEL_NAME', 'Automatic')
param monthlyAgentUnitLimit = int(readEnvironmentVariable('SRE_AGENT_MONTHLY_AGENT_UNIT_LIMIT', '10000'))
param enableSandboxGroup = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_SANDBOX_GROUP', 'true'))
param enableWorkspaceTools = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_WORKSPACE_TOOLS', 'true'))
param initialSponsorGroupId = readEnvironmentVariable('SRE_AGENT_INITIAL_SPONSOR_GROUP_ID', '')
param enableAgentSpace = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_AGENT_SPACE', 'false'))
param enablePrivateEndpoints = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_PRIVATE_ENDPOINTS', 'true'))
param vnetAddressPrefix = readEnvironmentVariable('SRE_AGENT_VNET_ADDRESS_PREFIX', '10.42.0.0/16')
param privateEndpointSubnetPrefix = readEnvironmentVariable('SRE_AGENT_PRIVATE_ENDPOINT_SUBNET_PREFIX', '10.42.1.0/24')
param privateDnsZoneResourceIds = {
  keyVault: readEnvironmentVariable('SRE_AGENT_PRIVATE_DNS_ZONE_ID_KEY_VAULT', '')
}
param linkExistingPrivateDnsZones = bool(readEnvironmentVariable('SRE_AGENT_LINK_EXISTING_PRIVATE_DNS_ZONES', 'true'))

// Passed through to the azd postdeploy hook for deploy.py content generation.
// Supported values: managed-identity, key-vault.
param intuneDiagnosticsAuthMode = readEnvironmentVariable('INTUNE_DIAGNOSTICS_AUTH_MODE', 'managed-identity')

// SRE tool endpoint URL consumed by FarSight tools at runtime.
// Set this to the AGT gateway URL from the main FarSight deployment.
param farsightApiBaseUrl = readEnvironmentVariable('SRE_AGENT_TOOL_ENDPOINT_URL', '')

// SRE tool endpoint token scope for managed identity authentication.
// Format: api://<farsight-api-app-id>/.default
// Example: azd env set SRE_AGENT_TOOL_ENDPOINT_SCOPE "api://<farsight-api-app-id>/.default"
param farsightApiScope = readEnvironmentVariable('SRE_AGENT_TOOL_ENDPOINT_SCOPE', '')
