param name string
param location string
param tags object
param administratorLogin string
@secure()
param administratorLoginPassword string
param databases array
@description('Production gets zone-redundant HA, larger SKU and longer backups')
param isProduction bool

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: name
  location: location
  tags: tags
  sku: isProduction
    ? { name: 'Standard_D2ds_v5', tier: 'GeneralPurpose' }
    : { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    backup: {
      backupRetentionDays: isProduction ? 35 : 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: isProduction ? 'ZoneRedundant' : 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: { activeDirectoryAuth: 'Disabled', passwordAuth: 'Enabled' }
  }
}

// Allows traffic from Azure services (Container Apps). For a locked-down
// deployment replace with VNet integration + private DNS (see docs).
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: server
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource dbs 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = [
  for db in databases: {
    parent: server
    name: db
    properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  }
]

output fqdn string = server.properties.fullyQualifiedDomainName
