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

@description('Optional operator/client IPv4 CIDR allowed through the ACR firewall so azd can read remote-build result metadata and registry tags from default-deny ACR.')
param acrClientFirewallAllowedIpRange string = ''

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

@description('Enable Entra workload-token enforcement for FarSight API machine-to-machine endpoints.')
param enableApiWorkloadAuth bool = false

@description('Allowed token audiences for FarSight API workload auth as CSV.')
param apiAllowedAudiences string = ''

@description('Allowed caller service principal object IDs for FarSight API workload auth as CSV.')
param apiAllowedServicePrincipalObjectIds string = ''

@description('Required FarSight API app role value in caller token when workload auth is enabled. Leave empty to skip role enforcement.')
param apiRequiredAppRole string = ''

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

@description('Enable device client certificate authentication for the API.')
param enableApiDeviceCertAuth bool = false

@secure()
@description('Base64-encoded PEM of the trusted root/issuing CA for device certificates. Required if enableApiDeviceCertAuth is true.')
param apiDeviceCertTrustedCaPem string = ''

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

@description('Initial image for the API Container App before azd deploy publishes the service image.')
param apiPlaceholderImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Initial image for the admin web Container App before azd deploy publishes the service image.')
param adminPlaceholderImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Initial image for the agent tools Container App before azd deploy publishes the service image.')
param toolsPlaceholderImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

var namePrefix = 'farsight-${environmentName}'
var tags = {
  application: 'agent-azure-farsight'
  environment: environmentName
  managedBy: 'azd-bicep'
}
var effectiveAcrFirewallAllowedIpRanges = empty(acrClientFirewallAllowedIpRange) ? acrFirewallAllowedIpRanges : concat(acrFirewallAllowedIpRanges, [
  acrClientFirewallAllowedIpRange
])

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
    acrFirewallAllowedIpRanges: effectiveAcrFirewallAllowedIpRanges
    enableApim: enableApim
    enableDevEnrollmentApi: enableDevEnrollmentApi
    apiTenantId: tenant().tenantId
    enableApiWorkloadAuth: enableApiWorkloadAuth
    apiAllowedAudiences: apiAllowedAudiences
    apiAllowedServicePrincipalObjectIds: apiAllowedServicePrincipalObjectIds
    apiRequiredAppRole: apiRequiredAppRole
    adminGroupObjectIds: adminGroupObjectIds
    apiInternalAuthSecret: apiInternalAuthSecret
    enableApiDeviceCertAuth: enableApiDeviceCertAuth
    apiDeviceCertTrustedCaPem: apiDeviceCertTrustedCaPem
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
    apiPlaceholderImage: apiPlaceholderImage
    adminPlaceholderImage: adminPlaceholderImage
    toolsPlaceholderImage: toolsPlaceholderImage
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
