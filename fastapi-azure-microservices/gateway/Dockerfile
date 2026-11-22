# Edge gateway: single public entry point that routes /v1/* to internal services.
# Non-root nginx image listening on 8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY templates/ /etc/nginx/templates/
COPY snippets/ /etc/nginx/snippets/

# Overridden per environment. In Azure Container Apps, internal apps are
# reachable at <app>.internal.<env-domain>; nginx's resolver does not use DNS
# search domains, so pass fully qualified names there (see infra/main.bicep).
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    IDENTITY_SERVICE_URL=http://identity-service:8000 \
    ORDERS_SERVICE_URL=http://orders-service:8000 \
    NOTIFICATION_SERVICE_URL=http://notification-service:8000

EXPOSE 8080
