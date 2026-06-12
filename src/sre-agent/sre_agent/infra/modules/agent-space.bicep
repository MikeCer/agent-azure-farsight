// ============================================================
// Agent Space Module - Microsoft.App/agentSpaces
// ============================================================

@description('Azure region for resources.')
param location string

@description('Agent Space resource name.')
param agentSpaceName string

@description('Maximum number of agents allowed in this Agent Space.')
param maxAgentCount int = 15

@description('Tags applied to all resources.')
param tags object = {}

resource agentSpace 'Microsoft.App/agentSpaces@2026-01-01' = {
  name: agentSpaceName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    description: 'Agent-Azure-FarSight SRE Agent space'
    maxAgentCount: maxAgentCount
  }
}

output agentSpaceId string = agentSpace.id
output agentSpaceName string = agentSpace.name
