targetScope = 'resourceGroup'

@description('Deployment environment name, for example dev, test, or prod.')
param environmentName string

@description('Primary collector/control-plane location.')
param collectorLocation string = 'italynorth'

@description('Azure SRE Agent/tool gateway location.')
param agentLocation string = 'swedencentral'

@description('Allow public ingress for development and test environments.')
param enablePublicIngress bool = true

@description('Enable private endpoint-capable topology. Detailed private endpoint modules are added during hardening.')
param enablePrivateEndpoints bool = false

@description('Collector/control-plane virtual network address prefix.')
param vnetAddressPrefix string = '10.10.0.0/16'

@description('Collector/control-plane Container Apps infrastructure subnet prefix.')
param containerAppsInfrastructureSubnetPrefix string = '10.10.0.0/23'

@description('Collector/control-plane private endpoint subnet prefix.')
param privateEndpointSubnetPrefix string = '10.10.2.0/24'

@description('Optional collector/control-plane API Management subnet prefix. Used only when API Management private networking is enabled.')
param apimSubnetPrefix string = '10.10.3.0/24'

@description('Existing private DNS zone resource IDs keyed by service name for collector/control-plane private endpoint links.')
param privateDnsZoneResourceIds object = {
  storageBlob: ''
  keyVault: ''
  containerRegistry: ''
  cosmosSql: ''
  serviceBus: ''
  appConfiguration: ''
  apiManagement: ''
  azureMonitor: ''
  logAnalyticsOms: ''
  logAnalyticsOds: ''
  azureMonitorAgentSvc: ''
  containerAppsEnvironment: ''
}

@description('Link collector/control-plane private endpoints to the provided existing private DNS zones.')
param linkExistingPrivateDnsZones bool = true

@description('Agent gateway virtual network address prefix.')
param agentGatewayVnetAddressPrefix string = '10.20.0.0/16'

@description('Agent gateway Container Apps infrastructure subnet prefix.')
param agentGatewayContainerAppsInfrastructureSubnetPrefix string = '10.20.0.0/23'

@description('Agent gateway private endpoint subnet prefix.')
param agentGatewayPrivateEndpointSubnetPrefix string = '10.20.2.0/24'

@description('Existing private DNS zone resource IDs keyed by service name for agent gateway private endpoint links.')
param agentGatewayPrivateDnsZoneResourceIds object = {
  storageBlob: ''
  keyVault: ''
  containerRegistry: ''
  cosmosSql: ''
  serviceBus: ''
  appConfiguration: ''
  apiManagement: ''
  azureMonitor: ''
  logAnalyticsOms: ''
  logAnalyticsOds: ''
  azureMonitorAgentSvc: ''
  containerAppsEnvironment: ''
}

@description('Link agent gateway private endpoints to the provided existing private DNS zones.')
param agentGatewayLinkExistingPrivateDnsZones bool = true

@description('Enable optional API Management front door.')
param enableApim bool = false

@description('Enable development certificate enrollment API path.')
param enableDevEnrollmentApi bool = true

@description('Cosmos DB job retention in days.')
param cosmosJobRetentionDays int = 30

@description('Blob artifact retention in days.')
param artifactRetentionDays int = 30

@description('Log Analytics retention in days.')
param logAnalyticsRetentionDays int = 90

@description('Admin group object IDs allowed to manage FarSight.')
param adminGroupObjectIds array = []

var namePrefix = 'farsight-${environmentName}'
var tags = {
  application: 'agent-azure-farsight'
  environment: environmentName
  managedBy: 'azd-bicep'
}

module core 'modules/core.bicep' = {
  name: 'core-${environmentName}'
  params: {
    namePrefix: namePrefix
    location: collectorLocation
    tags: tags
    cosmosJobRetentionDays: cosmosJobRetentionDays
    artifactRetentionDays: artifactRetentionDays
    logAnalyticsRetentionDays: logAnalyticsRetentionDays
    enablePublicIngress: enablePublicIngress
    enablePrivateEndpoints: enablePrivateEndpoints
    enableApim: enableApim
    enableDevEnrollmentApi: enableDevEnrollmentApi
    adminGroupObjectIds: adminGroupObjectIds
    vnetAddressPrefix: vnetAddressPrefix
    containerAppsInfrastructureSubnetPrefix: containerAppsInfrastructureSubnetPrefix
    privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
    apimSubnetPrefix: apimSubnetPrefix
    privateDnsZoneResourceIds: privateDnsZoneResourceIds
    linkExistingPrivateDnsZones: linkExistingPrivateDnsZones
  }
}

module agentGateway 'modules/agent-gateway.bicep' = {
  name: 'agent-gateway-${environmentName}'
  params: {
    namePrefix: namePrefix
    location: agentLocation
    tags: tags
    logAnalyticsRetentionDays: logAnalyticsRetentionDays
    enablePublicIngress: enablePublicIngress
    enablePrivateEndpoints: enablePrivateEndpoints
    vnetAddressPrefix: agentGatewayVnetAddressPrefix
    containerAppsInfrastructureSubnetPrefix: agentGatewayContainerAppsInfrastructureSubnetPrefix
    privateEndpointSubnetPrefix: agentGatewayPrivateEndpointSubnetPrefix
    privateDnsZoneResourceIds: agentGatewayPrivateDnsZoneResourceIds
    linkExistingPrivateDnsZones: agentGatewayLinkExistingPrivateDnsZones
  }
}

output apiContainerAppName string = core.outputs.apiContainerAppName
output adminContainerAppName string = core.outputs.adminContainerAppName
output agentToolGatewayName string = agentGateway.outputs.agentToolGatewayName
output storageAccountName string = core.outputs.storageAccountName
output cosmosAccountName string = core.outputs.cosmosAccountName
output serviceBusNamespaceName string = core.outputs.serviceBusNamespaceName
output collectorVnetId string = core.outputs.vnetId
output collectorSubnetIds object = core.outputs.subnetIds
output collectorPrivateDnsZoneIds object = core.outputs.privateDnsZoneIds
output agentGatewayVnetId string = agentGateway.outputs.vnetId
output agentGatewaySubnetIds object = agentGateway.outputs.subnetIds
output agentGatewayPrivateDnsZoneIds object = agentGateway.outputs.privateDnsZoneIds
