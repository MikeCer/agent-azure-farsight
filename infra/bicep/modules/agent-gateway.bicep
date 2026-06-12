param namePrefix string
param location string
param tags object
param logAnalyticsRetentionDays int

var workspaceName = 'law-${namePrefix}-agent-${location}'
var appInsightsName = 'appi-${namePrefix}-agent-${location}'
var environmentName = 'cae-${namePrefix}-agent-${location}'
var toolGatewayName = 'ca-${namePrefix}-tools-${location}'
var identityName = 'id-${namePrefix}-tools-${location}'

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

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
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
  }
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
        external: true
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

// Azure SRE Agent service provisioning is intentionally not modeled here yet.
// The service currently creates its own managed identity, Application Insights,
// and Log Analytics resources. Wire its managed identity to FarSight once the
// ARM/Bicep resource type and custom tool deployment contract are confirmed.

output agentToolGatewayName string = toolGateway.name
output agentToolGatewayPrincipalId string = toolIdentity.properties.principalId
