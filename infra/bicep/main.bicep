targetScope = 'resourceGroup'

@description('Deployment environment name, for example dev, test, or prod.')
param environmentName string

@description('Primary collector/control-plane location.')
param collectorLocation string = 'italynorth'

@description('Allow public ingress for development and test environments.')
param enablePublicIngress bool = true

@description('Enable private endpoint-capable topology. Detailed private endpoint modules are added during hardening.')
param enablePrivateEndpoints bool = false

@description('Allow ACR Tasks and trusted Azure services to bypass ACR network rules. Required for AZD remote Docker builds when ACR is private/default-deny.')
param enableAcrTaskNetworkBypass bool = true

@description('IPv4 CIDR ranges allowed through the ACR firewall when private endpoints and remote builds are enabled. Defaults cover observed AzureContainerRegistry build ranges for Italy North and Sweden Central.')
param acrFirewallAllowedIpRanges array = [
  '4.232.51.192/26'
  '172.160.222.128/26'
]

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

@description('Create a NAT Gateway for collector/control-plane outbound internet from delegated service subnets.')
param enableNatGateway bool = false

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

@secure()
@description('Shared secret used by the admin BFF to sign privileged API calls during the current authorization phase.')
param apiInternalAuthSecret string = ''

@description('Enable Container Apps Easy Auth for the admin web application.')
param enableAdminEasyAuth bool = false

@description('Entra application/client ID for admin web Easy Auth.')
param adminAuthClientId string = ''

@secure()
@description('Client secret for admin web Easy Auth app registration.')
param adminAuthClientSecret string = ''

@secure()
@description('Base64-encoded 32-byte encryption secret for Container Apps Easy Auth.')
param adminAuthEncryptionSecret string = ''

@description('Issuer URL for admin web Easy Auth, for example https://login.microsoftonline.com/<tenant-id>/v2.0.')
param adminAuthIssuer string = ''

@description('Allowed token audiences for admin web Easy Auth.')
param adminAuthAllowedAudiences array = []

@description('Optional Container Apps auth token store SAS URL setting name. Leave empty to disable token store.')
param adminAuthTokenStoreSasUrlSettingName string = ''

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
    enableAcrTaskNetworkBypass: enableAcrTaskNetworkBypass
    acrFirewallAllowedIpRanges: acrFirewallAllowedIpRanges
    enableApim: enableApim
    enableDevEnrollmentApi: enableDevEnrollmentApi
    adminGroupObjectIds: adminGroupObjectIds
    apiInternalAuthSecret: apiInternalAuthSecret
    vnetAddressPrefix: vnetAddressPrefix
    containerAppsInfrastructureSubnetPrefix: containerAppsInfrastructureSubnetPrefix
    privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
    apimSubnetPrefix: apimSubnetPrefix
    privateDnsZoneResourceIds: privateDnsZoneResourceIds
    linkExistingPrivateDnsZones: linkExistingPrivateDnsZones
    enableNatGateway: enableNatGateway
    enableAdminEasyAuth: enableAdminEasyAuth
    adminAuthClientId: adminAuthClientId
    adminAuthClientSecret: adminAuthClientSecret
    adminAuthEncryptionSecret: adminAuthEncryptionSecret
    adminAuthIssuer: adminAuthIssuer
    adminAuthAllowedAudiences: adminAuthAllowedAudiences
    adminAuthTokenStoreSasUrlSettingName: adminAuthTokenStoreSasUrlSettingName
  }
}

output apiContainerAppName string = core.outputs.apiContainerAppName
output adminContainerAppName string = core.outputs.adminContainerAppName
output agentToolGatewayName string = core.outputs.agentToolGatewayName
output storageAccountName string = core.outputs.storageAccountName
output cosmosAccountName string = core.outputs.cosmosAccountName
output serviceBusNamespaceName string = core.outputs.serviceBusNamespaceName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = core.outputs.acrLoginServer
output collectorVnetId string = core.outputs.vnetId
output collectorSubnetIds object = core.outputs.subnetIds
output collectorPrivateDnsZoneIds object = core.outputs.privateDnsZoneIds
output collectorNatGatewayId string = core.outputs.natGatewayId
