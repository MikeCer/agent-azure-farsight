using './main.bicep'

param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'agent-azure-farsight-sre')
param location = readEnvironmentVariable('AZURE_LOCATION', 'westeurope')
param principalId = readEnvironmentVariable('AZURE_PRINCIPAL_ID', '')
param upgradeChannel = readEnvironmentVariable('SRE_AGENT_UPGRADE_CHANNEL', 'Stable')
param defaultModelProvider = readEnvironmentVariable('SRE_AGENT_DEFAULT_MODEL_PROVIDER', 'Anthropic')
param defaultModelName = readEnvironmentVariable('SRE_AGENT_DEFAULT_MODEL_NAME', 'Automatic')
param initialSponsorGroupId = readEnvironmentVariable('SRE_AGENT_INITIAL_SPONSOR_GROUP_ID', '')
param enableAgentSpace = bool(readEnvironmentVariable('SRE_AGENT_ENABLE_AGENT_SPACE', 'false'))

// Passed through to the azd postdeploy hook for deploy.py content generation.
// Supported values: key-vault, managed-identity.
param intuneDiagnosticsAuthMode = readEnvironmentVariable('INTUNE_DIAGNOSTICS_AUTH_MODE', 'key-vault')
