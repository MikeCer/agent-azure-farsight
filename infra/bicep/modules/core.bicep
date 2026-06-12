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

var normalizedPrefix = replace(toLower(namePrefix), '-', '')
var unique = take(uniqueString(resourceGroup().id, namePrefix), 8)
var storageAccountName = 'st${take(normalizedPrefix, 10)}${unique}'
var acrName = 'acr${take(normalizedPrefix, 16)}${unique}'
var keyVaultName = 'kv-${take(normalizedPrefix, 8)}-${unique}'
var appConfigName = 'appcs-${namePrefix}-${take(unique, 4)}'
var workspaceName = 'law-${namePrefix}-${location}'
var appInsightsName = 'appi-${namePrefix}-${location}'
var containerAppsEnvironmentName = 'cae-${namePrefix}-${location}'
var apiAppName = 'ca-${namePrefix}-api-${location}'
var adminAppName = 'ca-${namePrefix}-admin-${location}'
var workerAppName = 'ca-${namePrefix}-worker-${location}'
var serviceBusNamespaceName = 'sb-${namePrefix}-${take(unique, 4)}'
var cosmosAccountName = 'cosmos-${namePrefix}-${take(unique, 4)}'
var managedIdentityName = 'id-${namePrefix}-apps-${location}'
var artifactsContainerName = 'artifacts'

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
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvironmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiAppName
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
      ingress: {
        external: enablePublicIngress
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
      ingress: {
        external: enablePublicIngress
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
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
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
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
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
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
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
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
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
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

resource devEnrollmentSetting 'Microsoft.AppConfiguration/configurationStores/keyValues@2024-06-01' = {
  name: 'FarSight:Enrollment:EnableDevApi'
  parent: appConfig
  properties: {
    value: string(enableDevEnrollmentApi)
    contentType: 'text/plain'
  }
}

resource adminGroupsSetting 'Microsoft.AppConfiguration/configurationStores/keyValues@2024-06-01' = {
  name: 'FarSight:Admin:GroupObjectIds'
  parent: appConfig
  properties: {
    value: join(adminGroupObjectIds, ',')
    contentType: 'text/plain'
  }
}

resource optionalApim 'Microsoft.ApiManagement/service@2024-05-01' = if (enableApim) {
  name: 'apim-${namePrefix}-${take(unique, 4)}'
  location: location
  tags: tags
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  properties: {
    publisherEmail: 'security@example.invalid'
    publisherName: 'FarSight'
  }
}

output apiContainerAppName string = apiApp.name
output adminContainerAppName string = adminApp.name
output workerContainerAppName string = workerApp.name
output storageAccountName string = storage.name
output cosmosAccountName string = cosmos.name
output serviceBusNamespaceName string = serviceBus.name
output keyVaultName string = keyVault.name
output appConfigurationName string = appConfig.name
output acrName string = acr.name
