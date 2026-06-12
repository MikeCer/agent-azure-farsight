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
  }
}

module agentGateway 'modules/agent-gateway.bicep' = {
  name: 'agent-gateway-${environmentName}'
  params: {
    namePrefix: namePrefix
    location: agentLocation
    tags: tags
    logAnalyticsRetentionDays: logAnalyticsRetentionDays
  }
}

output apiContainerAppName string = core.outputs.apiContainerAppName
output adminContainerAppName string = core.outputs.adminContainerAppName
output agentToolGatewayName string = agentGateway.outputs.agentToolGatewayName
output storageAccountName string = core.outputs.storageAccountName
output cosmosAccountName string = core.outputs.cosmosAccountName
output serviceBusNamespaceName string = core.outputs.serviceBusNamespaceName
