# Lambda base image with Python 3.11
FROM public.ecr.aws/lambda/python:3.11

# Install system deps for Playwright Chromium
RUN yum install -y \
    wget unzip xorg-x11-server-Xvfb \
    libXcomposite libXcursor libXdamage libXext libXi libXtst \
    libnss3 libnspr4 \
    gtk3 alsa-lib \
    atk at-spi2-atk at-spi2-core \
    cups-libs dbus-glib dbus-libs \
    libdrm libxkbcommon libXrandr libXfixes libXrender libXss \
    p
