param namePrefix string
param location string
param tags object
param logAnalyticsRetentionDays int
param enablePublicIngress bool
param enablePrivateEndpoints bool

@description('Agent gateway virtual network address prefix.')
param vnetAddressPrefix string = '10.20.0.0/16'

@description('Agent gateway Container Apps infrastructure subnet prefix.')
param containerAppsInfrastructureSubnetPrefix string = '10.20.0.0/23'

@description('Agent gateway private endpoint subnet prefix.')
param privateEndpointSubnetPrefix string = '10.20.2.0/24'

@description('Existing private DNS zone resource IDs keyed by service name for agent gateway private endpoint links.')
param privateDnsZoneResourceIds object = {}

@description('Link agent gateway private endpoints to the provided existing private DNS zones.')
param linkExistingPrivateDnsZones bool = true

@description('Create a NAT Gateway for outbound internet from agent gateway service subnets.')
param enableNatGateway bool = false

var normalizedPrefix = replace(toLower(namePrefix), '-', '')
var unique = take(uniqueString(resourceGroup().id, namePrefix, location, 'agent-gateway'), 8)
var workspaceName = 'law-${namePrefix}-agent-${location}'
var appInsightsName = 'appi-${namePrefix}-agent-${location}'
var environmentName = 'cae-${namePrefix}-agent-${location}'
var toolGatewayName = 'ca-${namePrefix}-tools-${location}'
var identityName = 'id-${namePrefix}-tools-${location}'
var privateEndpointNamePrefix = 'pe-${take(normalizedPrefix, 24)}-${take(unique, 6)}-agent'
var monitorPrivateLinkScopeName = 'ampls-${namePrefix}-agent-${take(unique, 4)}'
var publicNetworkAccess = enablePrivateEndpoints ? 'Disabled' : 'Enabled'
var toolGatewayIngressExternal = enablePrivateEndpoints ? false : enablePublicIngress

module networking 'networking.bicep' = if (enablePrivateEndpoints) {
  name: 'networking-${namePrefix}-agent-${location}'
  params: {
    namePrefix: '${namePrefix}-agent'
    location: location
    tags: tags
    virtualNetworkAddressPrefix: vnetAddressPrefix
    containerAppsInfrastructureSubnetAddressPrefix: containerAppsInfrastructureSubnetPrefix
    privateEndpointsSubnetAddressPrefix: privateEndpointSubnetPrefix
    enableApiManagementSubnet: false
    enableNatGateway: enableNatGateway
    existingPrivateDnsZoneResourceIds: privateDnsZoneResourceIds
    linkExistingPrivateDnsZones: linkExistingPrivateDnsZones
  }
}

resource toolIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
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

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
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
  }, enablePrivateEndpoints ? {
    vnetConfiguration: {
      infrastructureSubnetId: networking!.outputs.containerAppsInfrastructureSubnetId
      internal: true
    }
  } : {})
}

resource toolGateway 'Microsoft.App/containerApps@2024-03-01' = {
  name: toolGatewayName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${toolIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: toolGatewayIngressExternal
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'agent-tools'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          env: [
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
        maxReplicas: 3
      }
    }
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

// Private Sweden Central ingress keeps the tool gateway off the public internet. The Italy North
// FarSight API still needs routable private connectivity (for example VNet peering or hub transit)
// plus DNS forwarding between these regional VNets; that cross-region routing is intentionally not
// modeled in this standalone module.
// Azure SRE Agent service provisioning is intentionally not modeled here yet.
// The service currently creates its own managed identity, Application Insights,
// and Log Analytics resources. Wire its managed identity to FarSight once the
// ARM/Bicep resource type and custom tool deployment contract are confirmed.

output agentToolGatewayName string = toolGateway.name
output agentToolGatewayPrincipalId string = toolIdentity.properties.principalId
output vnetId string = enablePrivateEndpoints ? networking!.outputs.vnetId : ''
output subnetIds object = enablePrivateEndpoints ? networking!.outputs.subnetIds : {}
output privateDnsZoneIds object = enablePrivateEndpoints ? networking!.outputs.privateDnsZoneIds : {}
output natGatewayId string = enablePrivateEndpoints && enableNatGateway ? networking!.outputs.natGatewayId : ''
output monitorPrivateLinkScopeName string = enablePrivateEndpoints ? monitorPrivateLinkScope.name : ''
