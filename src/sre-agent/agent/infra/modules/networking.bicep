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

@description('Existing Private DNS zone resource IDs keyed by service: keyVault, azureMonitor, logAnalyticsOms, logAnalyticsOds, azureMonitorAgentSvc. Empty values create zones in this resource group.')
param privateDnsZoneResourceIds object = {}

@description('Link existing Private DNS zones to the SRE Agent VNet. Zones created by this module are always linked.')
param linkExistingPrivateDnsZones bool = true

@description('Tags applied to resources.')
param tags object = {}

var privateEndpointSubnetName = 'snet-private-endpoints'
var normalizedPrivateDnsZoneResourceIds = union({
  keyVault: ''
  azureMonitor: ''
  logAnalyticsOms: ''
  logAnalyticsOds: ''
  azureMonitorAgentSvc: ''
}, privateDnsZoneResourceIds)
var privateDnsZoneNames = {
  keyVault: 'privatelink.vaultcore.azure.net'
  azureMonitor: 'privatelink.monitor.azure.com'
  logAnalyticsOms: 'privatelink.oms.opinsights.azure.com'
  logAnalyticsOds: 'privatelink.ods.opinsights.azure.com'
  azureMonitorAgentSvc: 'privatelink.agentsvc.azure-automation.net'
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

resource azureMonitorPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.azureMonitor)) {
  name: privateDnsZoneNames.azureMonitor
  location: 'global'
  tags: tags
}

resource logAnalyticsOmsPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms)) {
  name: privateDnsZoneNames.logAnalyticsOms
  location: 'global'
  tags: tags
}

resource logAnalyticsOdsPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds)) {
  name: privateDnsZoneNames.logAnalyticsOds
  location: 'global'
  tags: tags
}

resource azureMonitorAgentSvcPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc)) {
  name: privateDnsZoneNames.azureMonitorAgentSvc
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

resource azureMonitorPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.azureMonitor)) {
  parent: azureMonitorPrivateDnsZone
  name: 'vnet-${linkSuffix}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource logAnalyticsOmsPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms)) {
  parent: logAnalyticsOmsPrivateDnsZone
  name: 'vnet-${linkSuffix}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource logAnalyticsOdsPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds)) {
  parent: logAnalyticsOdsPrivateDnsZone
  name: 'vnet-${linkSuffix}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource azureMonitorAgentSvcPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (empty(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc)) {
  parent: azureMonitorAgentSvcPrivateDnsZone
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

module existingAzureMonitorPrivateDnsZoneLink 'private-dns-zone-link.bicep' = if (linkExistingPrivateDnsZones && !empty(normalizedPrivateDnsZoneResourceIds.azureMonitor)) {
  name: 'dns-link-monitor-${linkSuffix}'
  scope: resourceGroup(split(normalizedPrivateDnsZoneResourceIds.azureMonitor, '/')[2], split(normalizedPrivateDnsZoneResourceIds.azureMonitor, '/')[4])
  params: {
    privateDnsZoneName: last(split(normalizedPrivateDnsZoneResourceIds.azureMonitor, '/'))
    virtualNetworkId: vnet.id
    linkName: 'vnet-${linkSuffix}'
  }
}

module existingLogAnalyticsOmsPrivateDnsZoneLink 'private-dns-zone-link.bicep' = if (linkExistingPrivateDnsZones && !empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms)) {
  name: 'dns-link-oms-${linkSuffix}'
  scope: resourceGroup(split(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms, '/')[2], split(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms, '/')[4])
  params: {
    privateDnsZoneName: last(split(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms, '/'))
    virtualNetworkId: vnet.id
    linkName: 'vnet-${linkSuffix}'
  }
}

module existingLogAnalyticsOdsPrivateDnsZoneLink 'private-dns-zone-link.bicep' = if (linkExistingPrivateDnsZones && !empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds)) {
  name: 'dns-link-ods-${linkSuffix}'
  scope: resourceGroup(split(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds, '/')[2], split(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds, '/')[4])
  params: {
    privateDnsZoneName: last(split(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds, '/'))
    virtualNetworkId: vnet.id
    linkName: 'vnet-${linkSuffix}'
  }
}

module existingAzureMonitorAgentSvcPrivateDnsZoneLink 'private-dns-zone-link.bicep' = if (linkExistingPrivateDnsZones && !empty(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc)) {
  name: 'dns-link-agentsvc-${linkSuffix}'
  scope: resourceGroup(split(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc, '/')[2], split(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc, '/')[4])
  params: {
    privateDnsZoneName: last(split(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc, '/'))
    virtualNetworkId: vnet.id
    linkName: 'vnet-${linkSuffix}'
  }
}

output vnetId string = vnet.id
output privateEndpointSubnetId string = privateEndpointSubnet.id
output privateDnsZoneResourceIds object = {
  keyVault: empty(normalizedPrivateDnsZoneResourceIds.keyVault) ? keyVaultPrivateDnsZone.id : normalizedPrivateDnsZoneResourceIds.keyVault
  azureMonitor: empty(normalizedPrivateDnsZoneResourceIds.azureMonitor) ? azureMonitorPrivateDnsZone.id : normalizedPrivateDnsZoneResourceIds.azureMonitor
  logAnalyticsOms: empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOms) ? logAnalyticsOmsPrivateDnsZone.id : normalizedPrivateDnsZoneResourceIds.logAnalyticsOms
  logAnalyticsOds: empty(normalizedPrivateDnsZoneResourceIds.logAnalyticsOds) ? logAnalyticsOdsPrivateDnsZone.id : normalizedPrivateDnsZoneResourceIds.logAnalyticsOds
  azureMonitorAgentSvc: empty(normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc) ? azureMonitorAgentSvcPrivateDnsZone.id : normalizedPrivateDnsZoneResourceIds.azureMonitorAgentSvc
}
