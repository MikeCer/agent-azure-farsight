param namePrefix string
param location string
param tags object
param cosmosJobRetentionDays int
param artifactRetentionDays int
param logAnalyticsRetentionDays int
param enablePublicIngress bool
param enablePrivateEndpoints bool
param enableApim bool
param enableDevEnrollmentApi bool
param adminGroupObjectIds array

@description('Collector/control-plane virtual network address prefix.')
param vnetAddressPrefix string = '10.10.0.0/16'

@description('Collector/control-plane Container Apps infrastructure subnet prefix.')
param containerAppsInfrastructureSubnetPrefix string = '10.10.0.0/23'

@description('Collector/control-plane private endpoint subnet prefix.')
param privateEndpointSubnetPrefix string = '10.10.2.0/24'

@description('Optional collector/control-plane API Management subnet prefix. Used only when API Management private networking is enabled.')
param apimSubnetPrefix string = '10.10.3.0/24'

@description('Existing private DNS zone resource IDs keyed by service name for collector/control-plane private endpoint links.')
param privateDnsZoneResourceIds object = {}

@description('Link collector/control-plane private endpoints to the provided existing private DNS zones.')
param linkExistingPrivateDnsZones bool = true

@description('Create a NAT Gateway for outbound internet from collector/control-plane service subnets.')
param enableNatGateway bool = false

@description('Enable Container Apps Easy Auth for the admin web application.')
param enableAdminEasyAuth bool = false

@description('Entra application/client ID for admin web Easy Auth.')
param adminAuthClientId string = ''

@secure()
@description('Client secret for admin web Easy Auth app registration.')
param adminAuthClientSecret string = ''

@description('Issuer URL for admin web Easy Auth.')
param adminAuthIssuer string = ''

@description('Allowed token audiences for admin web Easy Auth.')
param adminAuthAllowedAudiences array = []

var normalizedPrefix = replace(toLower(namePrefix), '-', '')
var shortNamePrefix = replace(namePrefix, 'farsight-', 'fs-')
var regionCode = location == 'italynorth' ? 'itn' : (location == 'swedencentral' ? 'swc' : take(replace(toLower(location), '-', ''), 6))
var unique = take(uniqueString(resourceGroup().id, namePrefix), 8)
var storageAccountName = 'st${take(normalizedPrefix, 10)}${unique}'
var acrName = 'acr${take(normalizedPrefix, 16)}${unique}'
var keyVaultName = 'kv-${take(normalizedPrefix, 8)}-${unique}'
var appConfigName = 'appcs-${namePrefix}-${take(unique, 4)}'
var workspaceName = 'law-${namePrefix}-${location}'
var appInsightsName = 'appi-${namePrefix}-${location}'
var containerAppsEnvironmentName = 'cae-${namePrefix}-${location}'
var apiAppName = 'ca-${shortNamePrefix}-api-${regionCode}'
var adminAppName = 'ca-${shortNamePrefix}-admin-${regionCode}'
var workerAppName = 'ca-${shortNamePrefix}-worker-${regionCode}'
var serviceBusNamespaceName = 'sb-${namePrefix}-${take(unique, 4)}'
var cosmosAccountName = 'cosmos-${namePrefix}-${take(unique, 4)}'
var managedIdentityName = 'id-${namePrefix}-apps-${location}'
var artifactsContainerName = 'artifacts'
var privateEndpointNamePrefix = 'pe-${take(normalizedPrefix, 24)}-${take(unique, 6)}'
var monitorPrivateLinkScopeName = 'ampls-${namePrefix}-${take(unique, 4)}'
var publicNetworkAccess = enablePrivateEndpoints ? 'Disabled' : 'Enabled'
var containerAppIngressExternal = enablePrivateEndpoints ? false : enablePublicIngress
var cosmosBuiltInDataContributorRoleDefinitionId = resourceId('Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions', cosmosAccountName, '00000000-0000-0000-0000-000000000002')

module networking 'networking.bicep' = if (enablePrivateEndpoints) {
  name: 'networking-${namePrefix}-${location}'
  params: {
    namePrefix: namePrefix
    location: location
    tags: tags
    virtualNetworkAddressPrefix: vnetAddressPrefix
    containerAppsInfrastructureSubnetAddressPrefix: containerAppsInfrastructureSubnetPrefix
    privateEndpointsSubnetAddressPrefix: privateEndpointSubnetPrefix
    enableApiManagementSubnet: enableApim
    apiManagementSubnetAddressPrefix: apimSubnetPrefix
    enableNatGateway: enableNatGateway
    existingPrivateDnsZoneResourceIds: privateDnsZoneResourceIds
    linkExistingPrivateDnsZones: linkExistingPrivateDnsZones
  }
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: managedIdentityName
  location: location
  tags: tags
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    retentionInDays: logAnalyticsRetentionDays
    publicNetworkAccessForIngestion: publicNetworkAccess
    publicNetworkAccessForQuery: publicNetworkAccess
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    publicNetworkAccessForIngestion: publicNetworkAccess
    publicNetworkAccessForQuery: publicNetworkAccess
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: enablePrivateEndpoints ? 'Premium' : 'Standard'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: publicNetworkAccess
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvironmentName
  location: location
  tags: tags
  properties: union({
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }, enablePrivateEndpoints ? {
    vnetConfiguration: {
      infrastructureSubnetId: networking!.outputs.containerAppsInfrastructureSubnetId
      internal: true
    }
  } : {})
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiAppName
  location: location
  tags: union(tags, {
    'azd-service-name': 'api'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: enableAdminEasyAuth ? [
        {
          name: 'microsoft-provider-authentication-secret'
          value: adminAuthClientSecret
        }
      ] : []
      ingress: {
        external: containerAppIngressExternal
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          env: [
            {
              name: 'FARSIGHT_ENVIRONMENT'
              value: namePrefix
            }
            {
              name: 'FARSIGHT_ENABLE_DEV_ENROLLMENT_API'
              value: string(enableDevEnrollmentApi)
            }
            {
              name: 'FARSIGHT_ADMIN_GROUP_OBJECT_IDS'
              value: join(adminGroupObjectIds, ',')
            }
            {
              name: 'FARSIGHT_COSMOS_ENDPOINT'
              value: cosmos.properties.documentEndpoint
            }
            {
              name: 'FARSIGHT_COSMOS_DATABASE'
              value: database.name
            }
            {
              name: 'FARSIGHT_COSMOS_POLICIES_CONTAINER'
              value: 'policies'
            }
            {
              name: 'APPINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
      }
    }
  }
}

resource adminApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: adminAppName
  location: location
  tags: union(tags, {
    'azd-service-name': 'admin-web'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: containerAppIngressExternal
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'admin-web'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

resource adminAppAuthConfig 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (enableAdminEasyAuth) {
  #disable-next-line use-parent-property
  name: '${adminApp.name}/current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: adminAuthClientId
          clientSecretSettingName: 'microsoft-provider-authentication-secret'
          openIdIssuer: adminAuthIssuer
        }
        validation: {
          allowedAudiences: empty(adminAuthAllowedAudiences) ? [
            adminAuthClientId
          ] : adminAuthAllowedAudiences
        }
      }
    }
    encryptionSettings: {
      containerAppAuthEncryptionSecretName: 'microsoft-provider-authentication-secret'
    }
    login: {
      tokenStore: {
        enabled: true
      }
    }
  }
}

resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: serviceBusNamespaceName
  location: location
  tags: tags
  sku: {
    name: enablePrivateEndpoints ? 'Premium' : 'Standard'
    tier: enablePrivateEndpoints ? 'Premium' : 'Standard'
    capacity: enablePrivateEndpoints ? 1 : null
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: publicNetworkAccess
    disableLocalAuth: true
  }
}

resource jobsQueue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  name: 'jobs'
  parent: serviceBus
  properties: {
    requiresSession: true
    lockDuration: 'PT5M'
    maxDeliveryCount: 5
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'PT1H'
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  identity: {
    type: 'SystemAssigned'
  }

  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    publicNetworkAccess: publicNetworkAccess
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

resource appIdentityCosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  #disable-next-line use-parent-property
  name: '${cosmos.name}/${guid(cosmos.id, appIdentity.id, 'policies-container-data-contributor')}'
  properties: {
    roleDefinitionId: cosmosBuiltInDataContributorRoleDefinitionId
    principalId: appIdentity.properties.principalId
    scope: '${cosmos.id}/dbs/farsight'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  name: 'farsight'
  parent: cosmos
  properties: {
    resource: {
      id: 'farsight'
    }
  }
}

var containers = [
  {
    name: 'devices'
    partitionKey: '/tenantDeviceId'
    ttl: -1
  }
  {
    name: 'jobs'
    partitionKey: '/deviceId'
    ttl: cosmosJobRetentionDays * 86400
  }
  {
    name: 'approvals'
    partitionKey: '/approvalId'
    ttl: 90 * 86400
  }
  {
    name: 'manifests'
    partitionKey: '/manifestId'
    ttl: -1
  }
  {
    name: 'policies'
    partitionKey: '/policyId'
    ttl: -1
  }
  {
    name: 'investigations'
    partitionKey: '/incidentId'
    ttl: 90 * 86400
  }
  {
    name: 'artifactIndex'
    partitionKey: '/jobId'
    ttl: artifactRetentionDays * 86400
  }
  {
    name: 'auditEvents'
    partitionKey: '/correlationId'
    ttl: 180 * 86400
  }
]

resource cosmosContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for container in containers: {
  name: container.name
  parent: database
  properties: {
    resource: {
      id: container.name
      partitionKey: {
        paths: [
          container.partitionKey
        ]
        kind: 'Hash'
      }
      defaultTtl: container.ttl
    }
  }
}]

resource storage 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: publicNetworkAccess
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  name: 'default'
  parent: storage
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: artifactRetentionDays
    }
  }
}

resource artifactsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  name: artifactsContainerName
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

resource storageLifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2024-01-01' = {
  name: 'default'
  parent: storage
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-expired-artifacts'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              prefixMatch: [
                '${artifactsContainerName}/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: artifactRetentionDays
                }
              }
            }
          }
        }
      ]
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-12-01-preview' = {
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
    enablePurgeProtection: true
    enableSoftDelete: true
    publicNetworkAccess: publicNetworkAccess
  }
}

resource appConfig 'Microsoft.AppConfiguration/configurationStores@2024-06-01' = {
  name: appConfigName
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: publicNetworkAccess
  }
}

resource optionalApim 'Microsoft.ApiManagement/service@2024-05-01' = if (enableApim) {
  name: 'apim-${namePrefix}-${take(unique, 4)}'
  location: location
  tags: tags
  sku: {
    // API Management Consumption does not support inbound private endpoints; use Developer in private mode.
    name: enablePrivateEndpoints ? 'Developer' : 'Consumption'
    capacity: enablePrivateEndpoints ? 1 : 0
  }
  properties: {
    publisherEmail: 'security@example.invalid'
    publisherName: 'FarSight'
    publicNetworkAccess: publicNetworkAccess
  }
}

resource monitorPrivateLinkScope 'Microsoft.Insights/privateLinkScopes@2021-07-01-preview' = if (enablePrivateEndpoints) {
  name: monitorPrivateLinkScopeName
  location: 'global'
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource workspaceScopedResource 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = if (enablePrivateEndpoints) {
  parent: monitorPrivateLinkScope
  name: 'law-${take(unique, 4)}'
  properties: {
    linkedResourceId: workspace.id
  }
}

resource appInsightsScopedResource 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = if (enablePrivateEndpoints) {
  parent: monitorPrivateLinkScope
  name: 'appi-${take(unique, 4)}'
  properties: {
    linkedResourceId: appInsights.id
  }
}

resource acrPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-acr'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'acr-registry'
        properties: {
          privateLinkServiceId: acr.id
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

resource acrPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: acrPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'containerRegistry'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.containerRegistry
        }
      }
    ]
  }
}

resource serviceBusPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-sb'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'servicebus-namespace'
        properties: {
          privateLinkServiceId: serviceBus.id
          groupIds: [
            'namespace'
          ]
        }
      }
    ]
  }
}

resource serviceBusPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: serviceBusPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'serviceBus'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.serviceBus
        }
      }
    ]
  }
}

resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-cosmos'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'cosmos-sql'
        properties: {
          privateLinkServiceId: cosmos.id
          groupIds: [
            'Sql'
          ]
        }
      }
    ]
  }
}

resource cosmosPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: cosmosPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cosmosSql'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.cosmosSql
        }
      }
    ]
  }
}

resource storageBlobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-blob'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'storage-blob'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource storageBlobPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: storageBlobPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'storageBlob'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.storageBlob
        }
      }
    ]
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-kv'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'keyvault-vault'
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

resource keyVaultPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'keyVault'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.keyVault
        }
      }
    ]
  }
}

resource appConfigPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-appcs'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'appconfig-store'
        properties: {
          privateLinkServiceId: appConfig.id
          groupIds: [
            'configurationStores'
          ]
        }
      }
    ]
  }
}

resource appConfigPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: appConfigPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'appConfiguration'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.appConfiguration
        }
      }
    ]
  }
}

resource apimPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints && enableApim) {
  name: '${privateEndpointNamePrefix}-apim'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'apim-gateway'
        properties: {
          privateLinkServiceId: optionalApim.id
          groupIds: [
            'Gateway'
          ]
        }
      }
    ]
  }
}

resource apimPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints && enableApim) {
  parent: apimPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'apiManagement'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.apiManagement
        }
      }
    ]
  }
}

resource monitorPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enablePrivateEndpoints) {
  name: '${privateEndpointNamePrefix}-ampls'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: networking!.outputs.privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'azure-monitor'
        properties: {
          privateLinkServiceId: monitorPrivateLinkScope.id
          groupIds: [
            'azuremonitor'
          ]
        }
      }
    ]
  }
}

resource monitorPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (enablePrivateEndpoints) {
  parent: monitorPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'azureMonitor'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.azureMonitor
        }
      }
      {
        name: 'logAnalyticsOms'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.logAnalyticsOms
        }
      }
      {
        name: 'logAnalyticsOds'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.logAnalyticsOds
        }
      }
      {
        name: 'azureMonitorAgentSvc'
        properties: {
          privateDnsZoneId: networking!.outputs.privateDnsZoneIds.azureMonitorAgentSvc
        }
      }
    ]
  }
}

// Container Apps internal environments expose an environment-specific default domain after provisioning.
// Create/link the private DNS zone with networking.bicep once that DNS suffix is known by the deployment workflow.

output apiContainerAppName string = apiApp.name
output adminContainerAppName string = adminApp.name
output workerContainerAppName string = workerApp.name
output storageAccountName string = storage.name
output cosmosAccountName string = cosmos.name
output serviceBusNamespaceName string = serviceBus.name
output keyVaultName string = keyVault.name
output appConfigurationName string = appConfig.name
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output vnetId string = enablePrivateEndpoints ? networking!.outputs.vnetId : ''
output subnetIds object = enablePrivateEndpoints ? networking!.outputs.subnetIds : {}
output privateDnsZoneIds object = enablePrivateEndpoints ? networking!.outputs.privateDnsZoneIds : {}
output natGatewayId string = enablePrivateEndpoints && enableNatGateway ? networking!.outputs.natGatewayId : ''
output monitorPrivateLinkScopeName string = enablePrivateEndpoints ? monitorPrivateLinkScope.name : ''
