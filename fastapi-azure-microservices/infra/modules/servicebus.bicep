param name string
param location string
param tags object
param topicName string
param subscriptions array
param senderPrincipalIds array
param receiverPrincipalIds array

var senderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39' // Azure Service Bus Data Sender
var receiverRoleId = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0' // Azure Service Bus Data Receiver

resource namespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard' } // topics need Standard+
  properties: {
    minimumTlsVersion: '1.2'
    disableLocalAuth: true // SAS keys off: Entra ID / managed identity only
  }
}

resource topic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: namespace
  name: topicName
  properties: {
    defaultMessageTimeToLive: 'P14D'
    // Drops re-sends from the outbox relay (message_id == event id).
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT30M'
  }
}

resource subs 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = [
  for sub in subscriptions: {
    parent: topic
    name: sub
    properties: {
      lockDuration: 'PT1M'
      maxDeliveryCount: 10 // then -> dead-letter queue
      deadLetteringOnMessageExpiration: true
      defaultMessageTimeToLive: 'P14D'
    }
  }
]

resource senders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in senderPrincipalIds: {
    name: guid(topic.id, principalId, senderRoleId)
    scope: topic
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', senderRoleId)
    }
  }
]

resource receivers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in receiverPrincipalIds: {
    name: guid(topic.id, principalId, receiverRoleId)
    scope: topic
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', receiverRoleId)
    }
  }
]

output fullyQualifiedNamespace string = '${namespace.name}.servicebus.windows.net'
