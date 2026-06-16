// ============================================================
// Networking Module - VNet, private endpoint subnet, and DNS
// ============================================================

@description('Environment name used for deterministic link names.')
param environmentName string

@description('Azure region for regional networking resources.')
param location string

@description('Virtual network name.')
param vnetName string

@description('Address prefix reserved for the SRE Agent virtual network.')
param vnetAddressPrefix string

@description('Address prefix reserved for the SRE Agent private endpoint subnet.')
param privateEndpointSubnetPrefix string

@description('Existing Private DNS zone resource IDs keyed by service: keyVault. Empty value creates the zone in this resource group.')
param privateDnsZoneResourceIds object = {}

@description('Link existing Private DNS zones to the SRE Agent VNet. Zones created by this module are always linked.')
param linkExistingPrivateDnsZones bool = true

@description('Tags applied to resources.')
param tags object = {}

var privateEndpointSubnetName = 'snet-private-endpoints'
var normalizedPrivateDnsZoneResourceIds = union({
  keyVault: ''
}, privateDnsZoneResourceIds)
var privateDnsZoneNames = {
  keyVault: 'privatelink.vaultcore.azure.net'
}
var linkSuffix = uniqueString(resourceGroup().id, environmentName, vnetName)

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: privateEndpointSubnetName
  properties: {
    addressPrefix: privateEndpointSubnetPrefix
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

resource keyVaultPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.keyVault)) {
  name: privateDnsZoneNames.keyVault
  location: 'global'
  tags: tags
}

resource keyVaultPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.keyVault)) {
  parent: keyVaultPrivateDnsZone
  name: 'vnet-${linkSuffix}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

module existingKeyVaultPrivateDnsZoneLink 'private-dns-zone-link.bicep' = if (linkExistingPrivateDnsZones && !empty(normalizedPrivateDnsZoneResourceIds.keyVault)) {
  name: 'dns-link-kv-${linkSuffix}'
  scope: resourceGroup(split(normalizedPrivateDnsZoneResourceIds.keyVault, '/')[2], split(normalizedPrivateDnsZoneResourceIds.keyVault, '/')[4])
  params: {
    privateDnsZoneName: last(split(normalizedPrivateDnsZoneResourceIds.keyVault, '/'))
    virtualNetworkId: vnet.id
    linkName: 'vnet-${linkSuffix}'
  }
}

output vnetId string = vnet.id
output privateEndpointSubnetId string = privateEndpointSubnet.id
output privateDnsZoneResourceIds object = {
  keyVault: empty(normalizedPrivateDnsZoneResourceIds.keyVault) ? keyVaultPrivateDnsZone.id : normalizedPrivateDnsZoneResourceIds.keyVault
}
