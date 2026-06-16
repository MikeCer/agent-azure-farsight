// ============================================================
// Main Bicep - Agent-Azure-FarSight SRE Agent Deployment
//
// Deploys at subscription scope:
//   1. New resource group for SRE Agent resources
//   2. Log Analytics Workspace for SRE Agent internal logging
//   3. Application Insights for SRE Agent internal logging
//   4. User-assigned managed identity
//   5. SRE Agent (Microsoft.App/agents)
// ============================================================
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('Environment name. Drives the resource group name and resource suffixes.')
param environmentName string

@description('Primary Azure region for all new resources.')
@allowed(['westeurope', 'eastus2', 'australiaeast', 'swedencentral', 'italynorth'])
param location string = 'westeurope'

@description('Object ID of the deploying user. Receives SRE Agent Administrator role. Leave empty to skip.')
param principalId string = ''

@description('SRE Agent runtime upgrade channel. Stable creates the current non-preview agent generation.')
@allowed(['Stable', 'Preview'])
param upgradeChannel string = 'Stable'

@description('Default model provider for the SRE Agent runtime.')
@allowed(['Anthropic', 'MicrosoftFoundry'])
param defaultModelProvider string = 'Anthropic'

@description('Default model name for the SRE Agent runtime.')
param defaultModelName string = 'Automatic'

@description('Monthly SRE Agent unit cap for the resource.')
@minValue(1)
param monthlyAgentUnitLimit int = 10000

@description('Enable the newer SRE sandbox group feature.')
param enableSandboxGroup bool = true

@description('Enable newer workspace tool capabilities on the SRE Agent runtime.')
param enableWorkspaceTools bool = true

@description('Initial sponsor group ID used to initialize 2026 SRE Agent identity on first create. Leave empty for idempotent updates.')
param initialSponsorGroupId string = ''

@description('Create and attach a Microsoft.App/agentSpaces resource. Requires Agent Spaces to be enabled for the tenant/subscription.')
param enableAgentSpace bool = false

@description('Enable private endpoint-capable topology for SRE Agent dependencies.')
param enablePrivateEndpoints bool = true

@description('Address prefix reserved for the SRE Agent virtual network.')
param vnetAddressPrefix string = '10.42.0.0/16'

@description('Address prefix reserved for the SRE Agent private endpoint subnet.')
param privateEndpointSubnetPrefix string = '10.42.1.0/24'

@description('Existing Private DNS zone resource IDs keyed by service: keyVault. Empty value lets the networking module create the zone.')
param privateDnsZoneResourceIds object = {
  keyVault: ''
}

@description('Link the SRE Agent VNet to existing Private DNS zones when privateDnsZoneResourceIds are provided.')
param linkExistingPrivateDnsZones bool = true

@description('Auth mode for the intune_diagnostics_tool. Passed through to the azd postdeploy hook.')
@allowed(['key-vault', 'managed-identity'])
param intuneDiagnosticsAuthMode string = 'managed-identity'

@description('SRE tool endpoint URL. Passed through to the azd postdeploy hook so FarSight tools know which endpoint to call.')
param farsightApiBaseUrl string = ''

@description('SRE tool endpoint token scope for managed identity auth. Format: api://<app-id>/.default. Passed through to the azd postdeploy hook as SRE_AGENT_TOOL_ENDPOINT_SCOPE.')
param farsightApiScope string = ''

var tags = {
  'azd-env-name': environmentName
  purpose: 'agent-azure-farsight-sre-agent'
  'deployed-by': 'azd'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  scope: rg
  name: 'resources'
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    principalId: principalId
    upgradeChannel: upgradeChannel
    defaultModelProvider: defaultModelProvider
    defaultModelName: defaultModelName
    monthlyAgentUnitLimit: monthlyAgentUnitLimit
    enableSandboxGroup: enableSandboxGroup
    enableWorkspaceTools: enableWorkspaceTools
    initialSponsorGroupId: initialSponsorGroupId
    enableAgentSpace: enableAgentSpace
    enablePrivateEndpoints: enablePrivateEndpoints
    vnetAddressPrefix: vnetAddressPrefix
    privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
    privateDnsZoneResourceIds: privateDnsZoneResourceIds
    linkExistingPrivateDnsZones: linkExistingPrivateDnsZones
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output SRE_AGENT_NAME string = resources.outputs.agentName
output SRE_AGENT_ENDPOINT string = resources.outputs.agentEndpoint
output AGENT_PORTAL_URL string = resources.outputs.agentPortalUrl
output LOG_ANALYTICS_WORKSPACE_ID string = resources.outputs.logAnalyticsWorkspaceId
output APP_INSIGHTS_APP_ID string = resources.outputs.appInsightsAppId
output INTUNE_DIAGNOSTICS_AUTH_MODE string = intuneDiagnosticsAuthMode
output INTUNE_DIAGNOSTICS_KEY_VAULT_NAME string = resources.outputs.keyVaultName
output INTUNE_DIAGNOSTICS_KEY_VAULT_URI string = resources.outputs.keyVaultUri
output SRE_AGENT_SPACE_ID string = resources.outputs.agentSpaceId
output SRE_AGENT_TOOL_ENDPOINT_URL string = farsightApiBaseUrl
output SRE_AGENT_TOOL_ENDPOINT_SCOPE string = farsightApiScope
