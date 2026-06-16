// ============================================================
// Monitoring Access Module - Monitoring Reader role assignments
// Grants the SRE Agent identities telemetry read access so the
// Agent portal trace viewer can load Application Insights traces.
// ============================================================

@description('Application Insights resource ID.')
param appInsightsId string

@description('Log Analytics Workspace resource ID.')
param logAnalyticsWorkspaceId string

@description('Principal IDs (SRE Agent system-assigned and user-assigned identities) that read agent traces.')
param principalIds array

var monitoringReaderRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '43d0d8ad-25c7-4714-9337-8ba259a9fe05')

var appInsightsName = last(split(appInsightsId, '/'))
var logAnalyticsName = last(split(logAnalyticsWorkspaceId, '/'))

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource appInsightsMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: if (!empty(principalId)) {
  name: guid(appInsightsId, principalId, monitoringReaderRoleId)
  scope: appInsights
  properties: {
    roleDefinitionId: monitoringReaderRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
    description: 'Agent-Azure-FarSight SRE Agent - Monitoring Reader for trace viewer'
  }
}]

resource logAnalyticsMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: if (!empty(principalId)) {
  name: guid(logAnalyticsWorkspaceId, principalId, monitoringReaderRoleId)
  scope: logAnalytics
  properties: {
    roleDefinitionId: monitoringReaderRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
    description: 'Agent-Azure-FarSight SRE Agent - Monitoring Reader for trace viewer'
  }
}]
