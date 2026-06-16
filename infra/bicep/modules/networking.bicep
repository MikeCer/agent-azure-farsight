param namePrefix string

param location string = resourceGroup().location

param tags object = {}

@description('Optional override for the virtual network name. Defaults to vnet-{namePrefix}-{location}.')
param virtualNetworkName string = ''

@description('Address prefix for the FarSight virtual network.')
param virtualNetworkAddressPrefix string = '10.40.0.0/16'

@description('Name of the subnet delegated to Azure Container Apps managed environments.')
param containerAppsInfrastructureSubnetName string = 'snet-containerapps-infra'

@description('Address prefix for the Azure Container Apps infrastructure subnet.')
param containerAppsInfrastructureSubnetAddressPrefix string = '10.40.0.0/23'

@description('Name of the subnet used by private endpoints.')
param privateEndpointsSubnetName string = 'snet-private-endpoints'

@description('Address prefix for the private endpoints subnet.')
param privateEndpointsSubnetAddressPrefix string = '10.40.2.0/24'

@description('Create the optional API Management subnet.')
param enableApiManagementSubnet bool = false

@description('Name of the optional API Management subnet.')
param apiManagementSubnetName string = 'snet-apim'

@description('Address prefix for the optional API Management subnet.')
param apiManagementSubnetAddressPrefix string = '10.40.3.0/24'

@description('Create a NAT Gateway for outbound-capable non-Container-Apps subnets. Container Apps infrastructure subnets do not receive NAT Gateway association.')
param enableNatGateway bool = false

@description('Map of target private DNS zone keys to existing full resource IDs. Empty or omitted values create zones in this resource group.')
param existingPrivateDnsZoneResourceIds object = {}

@description('Link existing private DNS zones to this VNet when their full resource IDs are provided.')
param linkExistingPrivateDnsZones bool = false

@description('Private DNS zone name for the Container Apps managed environment private endpoint. Leave empty until the environment-specific zone name is known.')
param containerAppsEnvironmentPrivateDnsZoneName string = ''

var effectiveVirtualNetworkName = empty(virtualNetworkName) ? 'vnet-${namePrefix}-${location}' : virtualNetworkName

#disable-next-line no-hardcoded-env-urls
var storageBlobPrivateDnsZoneName = 'privatelink.blob.core.windows.net'
var keyVaultPrivateDnsZoneName = 'privatelink.vaultcore.azure.net'
var containerRegistryPrivateDnsZoneName = 'privatelink.azurecr.io'
var cosmosSqlPrivateDnsZoneName = 'privatelink.documents.azure.com'
var serviceBusPrivateDnsZoneName = 'privatelink.servicebus.windows.net'
var appConfigurationPrivateDnsZoneName = 'privatelink.azconfig.io'
var apiManagementPrivateDnsZoneName = 'privatelink.azure-api.net'

var storageBlobPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'storageBlob') ? string(existingPrivateDnsZoneResourceIds.storageBlob) : ''
var keyVaultPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'keyVault') ? string(existingPrivateDnsZoneResourceIds.keyVault) : ''
var containerRegistryPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'containerRegistry') ? string(existingPrivateDnsZoneResourceIds.containerRegistry) : ''
var cosmosSqlPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'cosmosSql') ? string(existingPrivateDnsZoneResourceIds.cosmosSql) : ''
var serviceBusPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'serviceBus') ? string(existingPrivateDnsZoneResourceIds.serviceBus) : ''
var appConfigurationPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'appConfiguration') ? string(existingPrivateDnsZoneResourceIds.appConfiguration) : ''
var apiManagementPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'apiManagement') ? string(existingPrivateDnsZoneResourceIds.apiManagement) : ''
var containerAppsEnvironmentPrivateDnsZoneId = contains(existingPrivateDnsZoneResourceIds, 'containerAppsEnvironment') ? string(existingPrivateDnsZoneResourceIds.containerAppsEnvironment) : ''

// Existing private DNS zones must be supplied as full ARM resource IDs. Bicep can then parse
// the subscription and resource group for cross-resource-group references; malformed or name-only
// values cannot be safely scoped.
var fallbackPrivateDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'placeholder.invalid')

var privateDnsZones = [
  {
    key: 'storageBlob'
    name: !empty(storageBlobPrivateDnsZoneId) ? last(split(storageBlobPrivateDnsZoneId, '/')) : storageBlobPrivateDnsZoneName
    existingId: storageBlobPrivateDnsZoneId
    subscriptionId: split(!empty(storageBlobPrivateDnsZoneId) ? storageBlobPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(storageBlobPrivateDnsZoneId) ? storageBlobPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'keyVault'
    name: !empty(keyVaultPrivateDnsZoneId) ? last(split(keyVaultPrivateDnsZoneId, '/')) : keyVaultPrivateDnsZoneName
    existingId: keyVaultPrivateDnsZoneId
    subscriptionId: split(!empty(keyVaultPrivateDnsZoneId) ? keyVaultPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(keyVaultPrivateDnsZoneId) ? keyVaultPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'containerRegistry'
    name: !empty(containerRegistryPrivateDnsZoneId) ? last(split(containerRegistryPrivateDnsZoneId, '/')) : containerRegistryPrivateDnsZoneName
    existingId: containerRegistryPrivateDnsZoneId
    subscriptionId: split(!empty(containerRegistryPrivateDnsZoneId) ? containerRegistryPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(containerRegistryPrivateDnsZoneId) ? containerRegistryPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'cosmosSql'
    name: !empty(cosmosSqlPrivateDnsZoneId) ? last(split(cosmosSqlPrivateDnsZoneId, '/')) : cosmosSqlPrivateDnsZoneName
    existingId: cosmosSqlPrivateDnsZoneId
    subscriptionId: split(!empty(cosmosSqlPrivateDnsZoneId) ? cosmosSqlPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(cosmosSqlPrivateDnsZoneId) ? cosmosSqlPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'serviceBus'
    name: !empty(serviceBusPrivateDnsZoneId) ? last(split(serviceBusPrivateDnsZoneId, '/')) : serviceBusPrivateDnsZoneName
    existingId: serviceBusPrivateDnsZoneId
    subscriptionId: split(!empty(serviceBusPrivateDnsZoneId) ? serviceBusPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(serviceBusPrivateDnsZoneId) ? serviceBusPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'appConfiguration'
    name: !empty(appConfigurationPrivateDnsZoneId) ? last(split(appConfigurationPrivateDnsZoneId, '/')) : appConfigurationPrivateDnsZoneName
    existingId: appConfigurationPrivateDnsZoneId
    subscriptionId: split(!empty(appConfigurationPrivateDnsZoneId) ? appConfigurationPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(appConfigurationPrivateDnsZoneId) ? appConfigurationPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'apiManagement'
    name: !empty(apiManagementPrivateDnsZoneId) ? last(split(apiManagementPrivateDnsZoneId, '/')) : apiManagementPrivateDnsZoneName
    existingId: apiManagementPrivateDnsZoneId
    subscriptionId: split(!empty(apiManagementPrivateDnsZoneId) ? apiManagementPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(apiManagementPrivateDnsZoneId) ? apiManagementPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
  {
    key: 'containerAppsEnvironment'
    name: !empty(containerAppsEnvironmentPrivateDnsZoneId) ? last(split(containerAppsEnvironmentPrivateDnsZoneId, '/')) : containerAppsEnvironmentPrivateDnsZoneName
    existingId: containerAppsEnvironmentPrivateDnsZoneId
    subscriptionId: split(!empty(containerAppsEnvironmentPrivateDnsZoneId) ? containerAppsEnvironmentPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[2]
    resourceGroupName: split(!empty(containerAppsEnvironmentPrivateDnsZoneId) ? containerAppsEnvironmentPrivateDnsZoneId : fallbackPrivateDnsZoneId, '/')[4]
  }
]

resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: effectiveVirtualNetworkName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        virtualNetworkAddressPrefix
      ]
    }
  }
}

var effectiveNatGatewayEnabled = enableNatGateway && enableApiManagementSubnet

resource natPublicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = if (effectiveNatGatewayEnabled) {
  name: 'pip-nat-${effectiveVirtualNetworkName}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2024-07-01' = if (effectiveNatGatewayEnabled) {
  name: 'nat-${effectiveVirtualNetworkName}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 4
    publicIpAddresses: [
      {
        id: natPublicIp.id
      }
    ]
  }
}

resource containerAppsInfrastructureSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  parent: vnet
  name: containerAppsInfrastructureSubnetName
  properties: {
    addressPrefix: containerAppsInfrastructureSubnetAddressPrefix
    delegations: [
      {
        name: 'container-apps-environment'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource privateEndpointsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  parent: vnet
  name: privateEndpointsSubnetName
  dependsOn: [
    containerAppsInfrastructureSubnet
  ]
  properties: {
    addressPrefix: privateEndpointsSubnetAddressPrefix
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

resource apiManagementSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = if (enableApiManagementSubnet) {
  parent: vnet
  name: apiManagementSubnetName
  dependsOn: [
    privateEndpointsSubnet
  ]
  properties: union({
    addressPrefix: apiManagementSubnetAddressPrefix
  }, effectiveNatGatewayEnabled ? {
    natGateway: {
      id: natGateway.id
    }
  } : {})
}

resource createdPrivateDnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for zone in privateDnsZones: if (empty(zone.existingId) && !empty(zone.name)) {
  name: zone.name
  location: 'global'
  tags: tags
}]

@batchSize(1)
resource createdPrivateDnsZoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (zone, zoneIndex) in privateDnsZones: if (empty(zone.existingId) && !empty(zone.name)) {
  parent: createdPrivateDnsZones[zoneIndex]
  name: 'vnet-link-${zone.key}-${take(uniqueString(vnet.id, zone.name), 8)}'
  location: 'global'
  dependsOn: [
    privateEndpointsSubnet
  ]
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

@batchSize(1)
module existingPrivateDnsZoneLinks 'private-dns-zone-link.bicep' = [for zone in privateDnsZones: if (!empty(zone.existingId) && linkExistingPrivateDnsZones) {
  name: 'dns-link-${zone.key}-${take(uniqueString(vnet.id, zone.existingId), 8)}'
  scope: resourceGroup(zone.subscriptionId, zone.resourceGroupName)
  dependsOn: [
    privateEndpointsSubnet
  ]
  params: {
    privateDnsZoneName: zone.name
    virtualNetworkId: vnet.id
    linkName: 'vnet-link-${zone.key}-${take(uniqueString(vnet.id, zone.existingId), 8)}'
  }
}]

output vnetId string = vnet.id
output subnetIds object = {
  containerAppsInfrastructure: containerAppsInfrastructureSubnet.id
  privateEndpoints: privateEndpointsSubnet.id
  apiManagement: enableApiManagementSubnet ? resourceId('Microsoft.Network/virtualNetworks/subnets', effectiveVirtualNetworkName, apiManagementSubnetName) : ''
}
output containerAppsInfrastructureSubnetId string = containerAppsInfrastructureSubnet.id
output privateEndpointsSubnetId string = privateEndpointsSubnet.id
output apiManagementSubnetId string = enableApiManagementSubnet ? resourceId('Microsoft.Network/virtualNetworks/subnets', effectiveVirtualNetworkName, apiManagementSubnetName) : ''
output natGatewayId string = effectiveNatGatewayEnabled ? natGateway.id : ''
output privateDnsZoneIds object = {
  storageBlob: !empty(storageBlobPrivateDnsZoneId) ? storageBlobPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', storageBlobPrivateDnsZoneName)
  keyVault: !empty(keyVaultPrivateDnsZoneId) ? keyVaultPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', keyVaultPrivateDnsZoneName)
  containerRegistry: !empty(containerRegistryPrivateDnsZoneId) ? containerRegistryPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', containerRegistryPrivateDnsZoneName)
  cosmosSql: !empty(cosmosSqlPrivateDnsZoneId) ? cosmosSqlPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', cosmosSqlPrivateDnsZoneName)
  serviceBus: !empty(serviceBusPrivateDnsZoneId) ? serviceBusPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', serviceBusPrivateDnsZoneName)
  appConfiguration: !empty(appConfigurationPrivateDnsZoneId) ? appConfigurationPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', appConfigurationPrivateDnsZoneName)
  apiManagement: !empty(apiManagementPrivateDnsZoneId) ? apiManagementPrivateDnsZoneId : resourceId('Microsoft.Network/privateDnsZones', apiManagementPrivateDnsZoneName)
  containerAppsEnvironment: !empty(containerAppsEnvironmentPrivateDnsZoneId) ? containerAppsEnvironmentPrivateDnsZoneId : (!empty(containerAppsEnvironmentPrivateDnsZoneName) ? resourceId('Microsoft.Network/privateDnsZones', containerAppsEnvironmentPrivateDnsZoneName) : '')
}
output privateDnsZoneNames object = {
  storageBlob: !empty(storageBlobPrivateDnsZoneId) ? last(split(storageBlobPrivateDnsZoneId, '/')) : storageBlobPrivateDnsZoneName
  keyVault: !empty(keyVaultPrivateDnsZoneId) ? last(split(keyVaultPrivateDnsZoneId, '/')) : keyVaultPrivateDnsZoneName
  containerRegistry: !empty(containerRegistryPrivateDnsZoneId) ? last(split(containerRegistryPrivateDnsZoneId, '/')) : containerRegistryPrivateDnsZoneName
  cosmosSql: !empty(cosmosSqlPrivateDnsZoneId) ? last(split(cosmosSqlPrivateDnsZoneId, '/')) : cosmosSqlPrivateDnsZoneName
  serviceBus: !empty(serviceBusPrivateDnsZoneId) ? last(split(serviceBusPrivateDnsZoneId, '/')) : serviceBusPrivateDnsZoneName
  appConfiguration: !empty(appConfigurationPrivateDnsZoneId) ? last(split(appConfigurationPrivateDnsZoneId, '/')) : appConfigurationPrivateDnsZoneName
  apiManagement: !empty(apiManagementPrivateDnsZoneId) ? last(split(apiManagementPrivateDnsZoneId, '/')) : apiManagementPrivateDnsZoneName
  containerAppsEnvironment: !empty(containerAppsEnvironmentPrivateDnsZoneId) ? last(split(containerAppsEnvironmentPrivateDnsZoneId, '/')) : containerAppsEnvironmentPrivateDnsZoneName
}
