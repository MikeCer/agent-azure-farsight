// ============================================================
// Monitoring Module - Log Analytics Workspace + Application Insights
// ============================================================

@description('Azure region for resources.')
param location string

@description('Log Analytics Workspace name.')
param logAnalyticsName string

@description('Application Insights name.')
param appInsightsName string

@description('Tags applied to all resources.')
param tags object = {}

@description('Create Azure Monitor private link resources and disable public ingestion/query.')
param enablePrivateEndpoints bool = false

@description('Subnet resource ID for Azure Monitor private endpoint placement.')
param privateEndpointSubnetId string = ''

@description('Private DNS zone resource ID for privatelink.monitor.azure.com.')
param azureMonitorPrivateDnsZoneId string = ''

@description('Private DNS zone resource ID for privatelink.oms.opinsights.azure.com.')
param logAnalyticsOmsPrivateDnsZoneId string = ''

@description('Private DNS zone resource ID for privatelink.ods.opinsights.azure.com.')
param logAnalyticsOdsPrivateDnsZoneId string = ''

@description('Private DNS zone resource ID for privatelink.agentsvc.azure-automation.net.')
param azureMonitorAgentSvcPrivateDnsZoneId string = ''

var monitorPrivateDnsZones = concat(
  !empty(azureMonitorPrivateDnsZoneId) ? [
    {
      name: 'azureMonitor'
      id: azureMonitorPrivateDnsZoneId
    }
  ] : [],
  !empty(logAnalyticsOmsPrivateDnsZoneId) ? [
    {
      name: 'logAnalyticsOms'
      id: logAnalyticsOmsPrivateDnsZoneId
    }
  ] : [],
  !empty(logAnalyticsOdsPrivateDnsZoneId) ? [
    {
      name: 'logAnalyticsOds'
      id: logAnalyticsOdsPrivateDnsZoneId
    }
  ] : [],
  !empty(azureMonitorAgentSvcPrivateDnsZoneId) ? [
    {
      name: 'azureMonitorAgentSvc'
      id: azureMonitorAgentSvcPrivateDnsZoneId
    }
  ] : []
)

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    publicNetworkAccessForQuery: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    Request_Source: 'IbizaAIExtension'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    publicNetworkAccessForIngestion: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    publicNetworkAccessForQuery: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

resource azureMonitorPrivateLinkScope 'Microsoft.Insights/privateLinkScopes@2021-09-01' = if (enablePrivateEndpoints) {
  name: 'ampls-${uniqueString(resourceGroup().id, logAnalyticsName, appInsightsName)}'
  location: 'global'
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource logAnalyticsScopedResource 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = if (enablePrivateEndpoints) {
  parent: azureMonitorPrivateLinkScope
  name: 'law-${uniqueString(logAnalyticsWorkspace.id)}'
  properties: {
    linkedResourceId: logAnalyticsWorkspace.id
  }
}

resource applicationInsightsScopedResource 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = if (enablePrivateEndpoints) {
  parent: azureMonitorPrivateLinkScope
  name: 'appi-${uniqueString(applicationInsights.id)}'
  properties: {
    linkedResourceId: applicationInsights.id
  }
}

resource azureMonitorPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enablePrivateEndpoints) {
  name: 'pe-${azureMonitorPrivateLinkScope.name}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'pls-${azureMonitorPrivateLinkScope.name}'
        properties: {
          privateLinkServiceId: azureMonitorPrivateLinkScope.id
          groupIds: [
            'azuremonitor'
          ]
        }
      }
    ]
  }
  dependsOn: [
    logAnalyticsScopedResource
    applicationInsightsScopedResource
  ]
}

resource azureMonitorPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (enablePrivateEndpoints && length(monitorPrivateDnsZones) > 0) {
  parent: azureMonitorPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      for zone in monitorPrivateDnsZones: {
        name: zone.name
        properties: {
          privateDnsZoneId: zone.id
        }
      }
    ]
  }
}

output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id
output logAnalyticsWorkspaceName string = logAnalyticsWorkspace.name
output appInsightsId string = applicationInsights.id
output appInsightsAppId string = applicationInsights.properties.AppId
output appInsightsConnectionString string = applicationInsights.properties.ConnectionString
output azureMonitorPrivateLinkScopeId string = enablePrivateEndpoints ? azureMonitorPrivateLinkScope.id : ''
output azureMonitorPrivateEndpointId string = enablePrivateEndpoints ? azureMonitorPrivateEndpoint.id : ''
