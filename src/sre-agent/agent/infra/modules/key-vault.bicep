// ============================================================
// Key Vault Module - Intune diagnostics runtime secrets
// ============================================================

@description('Azure region for resources.')
param location string

@description('Key Vault name.')
param keyVaultName string

@description('Principal ID of the SRE Agent user-assigned managed identity.')
param agentIdentityPrincipalId string

@description('Object ID of the deploying user. Receives Key Vault Secrets Officer role. Leave empty to skip.')
param principalId string = ''

@description('Tags applied to all resources.')
param tags object = {}

@description('Create a private endpoint for Key Vault and disable public network access.')
param enablePrivateEndpoints bool = false

@description('Subnet resource ID for Key Vault private endpoint placement.')
param privateEndpointSubnetId string = ''

@description('Private DNS zone resource ID for privatelink.vaultcore.azure.net.')
param privateDnsZoneId string = ''

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enablePrivateEndpoints) {
  name: 'pe-${keyVaultName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'pls-${keyVaultName}'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource keyVaultPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (enablePrivateEndpoints && !empty(privateDnsZoneId)) {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'keyVault'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

resource agentSecretsUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, agentIdentityPrincipalId, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: agentIdentityPrincipalId
    principalType: 'ServicePrincipal'
    description: 'Allow Agent-Azure-FarSight SRE Agent identity to read Intune diagnostics runtime secrets.'
  }
}

resource deployerSecretsOfficerRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(keyVault.id, principalId, keyVaultSecretsOfficerRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: principalId
    principalType: 'User'
    description: 'Allow deploying user to add Intune diagnostics secrets after deployment.'
  }
}

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output keyVaultPrivateEndpointId string = enablePrivateEndpoints ? keyVaultPrivateEndpoint.id : ''
