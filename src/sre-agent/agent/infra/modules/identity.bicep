// ============================================================
// Identity Module - User-Assigned Managed Identity
// ============================================================

@description('Azure region for resources.')
param location string

@description('User-assigned managed identity name.')
param identityName string

@description('Tags applied to all resources.')
param tags object = {}

resource userAssignedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: location
  tags: tags
  properties: {
    isolationScope: 'Regional'
  }
}

output identityId string = userAssignedIdentity.id
output identityName string = userAssignedIdentity.name
output identityPrincipalId string = userAssignedIdentity.properties.principalId
