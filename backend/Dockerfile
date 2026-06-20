FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install PowerShell Core
RUN apt-get update && apt-get install -y \
    wget \
    apt-transport-https \
    software-properties-common \
    python3.11 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && apt-get update \
    && apt-get install -y powershell \
    && rm -rf /var/lib/apt/lists/*

# Pre-install ExchangeOnlineManagement module in the image
RUN pwsh -NoLogo -NoProfile -Command \
    'Set-PSRepository -Name PSGallery -InstallationPolicy Trusted; \
     Install-Module -Name ExchangeOnlineManagement -Force -AllowClobber -Scope AllUsers -SkipPublisherCheck'

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
