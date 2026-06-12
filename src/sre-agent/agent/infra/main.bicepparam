using './main.bicep'

param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'agent-azure-farsight-sre')
param location = readEnvironmentVariable('AZURE_LOCATION', 'westeurope')
param principalId = readEnvironmentVariable('AZURE_PRINCIPAL_ID', '')
param upgradeChannel = readEnvironmentVariable('SRE_AGENT_UPGRADE_CHANNEL', 'Stable')
param defaultModelProvider = readEnvironmentVariable('SRE_AGENT_DEFAULT_MODEL_PROVIDER', 'Anthropic')
param defaultModelName = readEnvironmentVariable('SRE_AGENT_DEFAULT_MODEL_NAME', 'Automatic')
param initialSponsorGroupId = readEnvironmentVariable('SRE_AGENT_INITIAL_SPONSOR_GROUP_ID', '')
param enableAgentSpace = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_AGENT_SPACE', 'false'))
param enablePrivateEndpoints = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_PRIVATE_ENDPOINTS', 'true'))
param vnetAddressPrefix = readEnvironmentVariable('SRE_AGENT_VNET_ADDRESS_PREFIX', '10.42.0.0/16')
param privateEndpointSubnetPrefix = readEnvironmentVariable('SRE_AGENT_PRIVATE_ENDPOINT_SUBNET_PREFIX', '10.42.1.0/24')
param privateDnsZoneResourceIds = {
  keyVault: readEnvironmentVariable('SRE_AGENT_PRIVATE_DNS_ZONE_ID_KEY_VAULT', '')
  azureMonitor: readEnvironmentVariable('SRE_AGENT_PRIVATE_DNS_ZONE_ID_AZURE_MONITOR', '')
  logAnalyticsOms: readEnvironmentVariable('SRE_AGENT_PRIVATE_DNS_ZONE_ID_LOG_ANALYTICS_OMS', '')
  logAnalyticsOds: readEnvironmentVariable('SRE_AGENT_PRIVATE_DNS_ZONE_ID_LOG_ANALYTICS_ODS', '')
  azureMonitorAgentSvc: readEnvironmentVariable('SRE_AGENT_PRIVATE_DNS_ZONE_ID_AZURE_MONITOR_AGENT_SVC', '')
}
param linkExistingPrivateDnsZones = bool(readEnvironmentVariable('SRE_AGENT_LINK_EXISTING_PRIVATE_DNS_ZONES', 'true'))

// Passed through to the azd postdeploy hook for deploy.py content generation.
// Supported values: key-vault, managed-identity.
param intuneDiagnosticsAuthMode = readEnvironmentVariable('INTUNE_DIAGNOSTICS_AUTH_MODE', 'key-vault')
