targetScope = 'resourceGroup'

@description('Azure region for the test lab.')
param location string = resourceGroup().location

@description('Environment name used for resource naming and tags.')
param environmentName string = 'farsight-test'

@description('Number of Windows 11 test VMs to deploy.')
@minValue(1)
@maxValue(5)
param vmCount int = 2

@description('Low-cost VM size for Windows 11 test clients. Override if the image or workload requires more resources.')
param vmSize string = 'Standard_B2s'

@description('Local administrator username for the test VMs.')
param adminUsername string

@secure()
@description('Local administrator password for the test VMs.')
param adminPassword string

@description('Virtual network address prefix for the test lab.')
param vnetAddressPrefix string = '10.70.0.0/16'

@description('Subnet address prefix for Windows 11 test VMs.')
param subnetAddressPrefix string = '10.70.1.0/24'

@description('Create public IP addresses and allow inbound RDP from approved source prefixes. Keep false unless explicitly needed for break-glass testing.')
param enablePublicIp bool = false

@description('Allowed source prefixes for RDP when public IPs are enabled. Leave empty to deny internet RDP.')
param allowedRdpSourceAddressPrefixes array = []

@description('Create a NAT Gateway for outbound internet from the Windows 11 VM subnet. This is useful for Intune enrollment when VMs have no public IPs.')
param enableNatGateway bool = false

@description('Windows 11 image publisher.')
param imagePublisher string = 'MicrosoftWindowsDesktop'

@description('Windows 11 image offer.')
param imageOffer string = 'windows-11'

@description('Windows 11 image SKU. Override if unavailable in the selected subscription/region.')
param imageSku string = 'win11-24h2-pro'

@description('Windows 11 image version.')
param imageVersion string = 'latest'

@description('OS disk type for low-cost test lab VMs.')
@allowed([
  'Standard_LRS'
  'StandardSSD_LRS'
  'Premium_LRS'
])
param osDiskType string = 'StandardSSD_LRS'

var sanitizedEnvironment = take(replace(toLower(environmentName), '-', ''), 12)
var namePrefix = 'farsight-${sanitizedEnvironment}'
var vmSubnetName = 'snet-win11-test'
var tags = {
  application: 'agent-azure-farsight'
  environment: environmentName
  purpose: 'intune-collector-test-lab'
  costProfile: 'low-cost-dev-test'
}
var allRdpAllowRules = [for (prefix, index) in allowedRdpSourceAddressPrefixes: {
  name: 'AllowRdpFromApprovedSource${index}'
  properties: {
    priority: 100 + index
    access: 'Allow'
    direction: 'Inbound'
    protocol: 'Tcp'
    sourceAddressPrefix: prefix
    sourcePortRange: '*'
    destinationAddressPrefix: '*'
    destinationPortRange: '3389'
    description: 'Break-glass RDP source explicitly approved for the test lab.'
  }
}]
var rdpAllowRules = enablePublicIp ? allRdpAllowRules : []

resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: 'vnet-${namePrefix}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
  }
}

resource natPublicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = if (enableNatGateway) {
  name: 'pip-nat-${namePrefix}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2024-07-01' = if (enableNatGateway) {
  name: 'nat-${namePrefix}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 4
    publicIpAddresses: [
      {
        id: natPublicIp.id
      }
    ]
  }
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-07-01' = {
  name: 'nsg-${namePrefix}-win11'
  location: location
  tags: tags
  properties: {
    securityRules: concat(
      [
        {
          name: 'DenyInternetRdpByDefault'
          properties: {
            priority: 4096
            access: 'Deny'
            direction: 'Inbound'
            protocol: 'Tcp'
            sourceAddressPrefix: 'Internet'
            sourcePortRange: '*'
            destinationAddressPrefix: '*'
            destinationPortRange: '3389'
            description: 'Default deny for public RDP. Use Bastion, private connectivity, or explicit break-glass allow rules.'
          }
        }
      ],
      rdpAllowRules
    )
  }
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: vmSubnetName
  parent: vnet
  properties: union({
    addressPrefix: subnetAddressPrefix
    networkSecurityGroup: {
      id: nsg.id
    }
  }, enableNatGateway ? {
    natGateway: {
      id: natGateway.id
    }
  } : {})
}

resource publicIps 'Microsoft.Network/publicIPAddresses@2024-07-01' = [for i in range(0, vmCount): if (enablePublicIp) {
  name: 'pip-${namePrefix}-win11-${i + 1}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    publicIPAllocationMethod: 'Dynamic'
  }
}]

resource nics 'Microsoft.Network/networkInterfaces@2024-07-01' = [for i in range(0, vmCount): {
  name: 'nic-${namePrefix}-win11-${i + 1}'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: union({
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: subnet.id
          }
        }, enablePublicIp ? {
          publicIPAddress: {
            id: publicIps[i].id
          }
        } : {})
      }
    ]
  }
}]

resource vms 'Microsoft.Compute/virtualMachines@2024-11-01' = [for i in range(0, vmCount): {
  name: 'vm-${namePrefix}-win11-${i + 1}'
  location: location
  tags: tags
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    osProfile: {
      computerName: 'fswin11${i + 1}'
      adminUsername: adminUsername
      adminPassword: adminPassword
      windowsConfiguration: {
        provisionVMAgent: true
        enableAutomaticUpdates: true
        patchSettings: {
          patchMode: 'AutomaticByOS'
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: imagePublisher
        offer: imageOffer
        sku: imageSku
        version: imageVersion
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: osDiskType
        }
        deleteOption: 'Delete'
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nics[i].id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}]

output virtualNetworkName string = vnet.name
output subnetName string = subnet.name
output vmNames array = [for i in range(0, vmCount): vms[i].name]
output privateIpAddresses array = [for i in range(0, vmCount): nics[i].properties.ipConfigurations[0].properties.privateIPAddress]
output natGatewayId string = enableNatGateway ? natGateway.id : ''
output intuneEnrollmentNote string = 'After deployment, sign in with licensed Entra users and complete Entra join/Intune enrollment according to tenant policy. Bicep does not enroll these VMs into Intune by itself.'
