# Egress proxy: the only route out of the sandbox network. tinyproxy with a
# default-deny filter: CONNECT is allowed only to the hosts in allowlist.txt
# (model APIs). Everything else, including plain HTTP, is refused.
FROM alpine:3.20
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allowlist.txt /etc/tinyproxy/allowlist.txt
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
