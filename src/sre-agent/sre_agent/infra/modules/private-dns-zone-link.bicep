// ============================================================
// Private DNS Zone Link Module - link an existing zone to a VNet
// ============================================================

@description('Existing Private DNS zone name.')
param privateDnsZoneName string

@description('Virtual network resource ID to link to the Private DNS zone.')
param virtualNetworkId string

@description('Virtual network link name.')
param linkName string

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: privateDnsZoneName
}

resource virtualNetworkLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: linkName
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

output virtualNetworkLinkId string = virtualNetworkLink.id
