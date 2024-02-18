FROM ubuntu:22.04

ENV KUBE_VERSION 1.27.5
ENV PYTHON_VERSION=3.10

RUN apt-get update -y && apt-get install -y bash git curl net-tools dnsutils podman wget \ 
    && wget -q https://storage.googleapis.com/kubernetes-release/release/v${KUBE_VERSION}/bin/linux/amd64/kubectl -O /usr/local/bin/kubectl  \
    && chmod +x /usr/local/bin/kubectl  && chmod g+rwx /root  && mkdir /config  && chmod g+rwx /config

RUN apt-get install -y python${PYTHON_VERSION} python3-pip vim 

RUN wget -qO /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc \
    && chmod a+x /usr/local/bin/mc

WORKDIR /config
