"""Azure Service Bus transport (topic + per-service subscription).

* Authenticates with Managed Identity via DefaultAzureCredential (the
  namespace has local/SAS auth disabled in infra/), so no secrets.
* `message_id = event.id` lets Service Bus duplicate detection drop
  re-sends from the transactional outbox.
* Failed messages are abandoned and retried; after `maxDeliveryCount`
  Service Bus moves them to the subscription's dead-letter queue.
"""

from azure.servicebus import ServiceBusMessage, ServiceBusReceivedMessage
from azure.servicebus.aio import ServiceBusClient, ServiceBusReceiver, ServiceBusSender
from pydantic import ValidationError

from orderflow_common.events.base import Event, EventBus, EventHandler, dispatch
from orderflow_common.logging import get_logger

logger = get_logger(__name__)


class AzureServiceBusEventBus(EventBus):
    def __init__(
        self,
        *,
        topic: str,
        connection_string: str | None = None,
        fully_qualified_namespace: str | None = None,
    ) -> None:
        if not (connection_string or fully_qualified_namespace):
            raise ValueError("connection_string or fully_qualified_namespace is required")
        self._topic = topic
        self._connection_string = connection_string
        self._namespace = fully_qualified_namespace
        self._client: ServiceBusClient | None = None
        self._sender: ServiceBusSender | None = None
        self._credential = None

    @property
    def client(self) -> ServiceBusClient:
        if self._client is None:
            raise RuntimeError("AzureServiceBusEventBus.start() was not called")
        return self._client

    async def start(self) -> None:
        if self._connection_string:
            self._client = ServiceBusClient.from_connection_string(self._connection_string)
        else:
            from azure.identity.aio import DefaultAzureCredential

            # In Container Apps, AZURE_CLIENT_ID selects the user-assigned identity.
            self._credential = DefaultAzureCredential()
            self._client = ServiceBusClient(self._namespace, self._credential)  # type: ignore[arg-type]

    async def close(self) -> None:
        if self._sender is not None:
            await self._sender.close()
        if self._client is not None:
            await self._client.close()
        if self._credential is not None:
            await self._credential.close()

    async def publish(self, event: Event) -> None:
        if self._sender is None:
            self._sender = self.client.get_topic_sender(topic_name=self._topic)
        message = ServiceBusMessage(
            body=event.model_dump_json(),
            message_id=str(event.id),
            content_type="application/json",
            subject=event.type,
            correlation_id=event.correlation_id,
            application_properties={"event_type": event.type, "source": event.source},
        )
        await self._sender.send_messages(message)

    async def consume(self, handler: EventHandler, *, subscription: str) -> None:
        receiver = self.client.get_subscription_receiver(
            topic_name=self._topic, subscription_name=subscription, prefetch_count=20
        )
        logger.info("consumer_started", transport="servicebus", topic=self._topic, sub=subscription)
        async with receiver:
            while True:
                batch = await receiver.receive_messages(max_message_count=20, max_wait_time=5)
                for message in batch:
                    await self._handle(receiver, message, handler)

    async def _handle(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        handler: EventHandler,
    ) -> None:
        try:
            event = Event.model_validate_json(b"".join(message.body))
        except (ValidationError, TypeError, ValueError) as exc:
            logger.error("event_deserialization_failed", message_id=message.message_id)
            await receiver.dead_letter_message(
                message, reason="deserialization_failed", error_description=str(exc)[:1000]
            )
            return
        try:
            await dispatch(handler, event)
        except Exception as exc:
            logger.warning(
                "event_handler_failed",
                event_id=str(event.id),
                type=event.type,
                delivery_count=message.delivery_count,
                error=str(exc),
            )
            await receiver.abandon_message(message)
            return
        await receiver.complete_message(message)
