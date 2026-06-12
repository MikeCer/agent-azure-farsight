// ============================================================
// SRE Agent Module - Microsoft.App/agents
// Creates the SRE Agent resource and assigns the SRE Agent
// Administrator role to the deploying user when principalId is set.
// ============================================================

@description('Azure region for resources.')
param location string

@description('SRE Agent resource name.')
param agentName string

@description('Agent Space resource ID referenced by this SRE Agent.')
param agentSpaceId string = ''

@description('Initial sponsor group ID used to initialize 2026 SRE Agent identity. Leave empty to skip agent identity initialization.')
param initialSponsorGroupId string = ''

@description('User-assigned managed identity resource ID.')
param identityId string

@description('Application Insights App ID used for SRE Agent internal logging.')
param appInsightsAppId string

@secure()
@description('Application Insights connection string used for SRE Agent internal logging.')
param appInsightsConnectionString string

@description('Application Insights resource ID used as hidden-link tag.')
param appInsightsId string

@description('Resource group ID registered as the managed resource for agent investigations.')
param managedResourceGroupId string

@description('Object ID of the deploying user. Receives SRE Agent Administrator role. Leave empty to skip.')
param principalId string = ''

@description('SRE Agent runtime upgrade channel.')
@allowed(['Stable', 'Preview'])
param upgradeChannel string = 'Stable'

@description('Default model provider for the SRE Agent runtime.')
@allowed(['Anthropic', 'MicrosoftFoundry'])
param defaultModelProvider string = 'Anthropic'

@description('Default model name for the SRE Agent runtime.')
param defaultModelName string = 'Automatic'

@description('Tags applied to all resources.')
param tags object = {}

var sreAgentAdminRoleId = 'e79298df-d852-4c6d-84f9-5d13249d1e55'
var agentSpaceProperties = !empty(agentSpaceId) ? {
  agentSpaceId: agentSpaceId
} : {}
var agentIdentityProperties = !empty(initialSponsorGroupId) ? {
  agentIdentity: {
    initialSponsorGroupId: initialSponsorGroupId
  }
} : {}

resource sreAgent 'Microsoft.App/agents@2026-01-01' = {
  name: agentName
  location: location
  tags: union(tags, {
    'hidden-link: /app-insights-resource-id': appInsightsId
  })
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: union({
    knowledgeGraphConfiguration: {
      managedResources: [
        managedResourceGroupId
      ]
      identity: identityId
    }
    actionConfiguration: {
      mode: 'Autonomous'
      identity: identityId
      accessLevel: 'Low'
    }
    logConfiguration: {
      applicationInsightsConfiguration: {
        appId: appInsightsAppId
        connectionString: appInsightsConnectionString
      }
    }
    upgradeChannel: upgradeChannel
    defaultModel: {
      provider: defaultModelProvider
      name: defaultModelName
    }
  }, agentSpaceProperties, agentIdentityProperties)
}

resource sreAgentAdminRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(sreAgent.id, principalId, sreAgentAdminRoleId)
  scope: sreAgent
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sreAgentAdminRoleId)
    principalId: principalId
    principalType: 'User'
    description: 'Agent-Azure-FarSight SRE Agent - Administrator access for deploying user'
  }
}

output agentName string = sreAgent.name
output agentId string = sreAgent.id
#disable-next-line BCP053
output agentEndpoint string = sreAgent.properties.agentEndpoint
output agentPortalUrl string = 'https://sre.azure.com'
output agentPrincipalId string = sreAgent.identity.principalId
