FROM golang:1.20-buster AS build-stage

WORKDIR /app
COPY ./analyzers/rolaguard_bruteforce_analyzer/lorawanwrapper/utils/*.go ./

# Install go dependencies
RUN go env -w GO111MODULE=off
RUN go get -d ./...

# Compile go library
RUN go build -o /lorawanWrapper.so -buildmode=c-shared jsonUnmarshaler.go lorawanWrapper.go micGenerator.go sessionKeysGenerator.go hashGenerator.go


FROM python:3.7-slim-buster

# Set the working directory to /app
WORKDIR /root/app

# Set variable env to allow deprecated package
ENV SKLEARN_ALLOW_DEPRECATED_SKLEARN_PACKAGE_INSTALL=True

# Add the python requirements first in order to docker cache them
COPY ./requirements.txt ./
RUN pip3 install --upgrade pip \
  && pip3 install --use-pep517 --upgrade --trusted-host pypi.python.org --no-cache-dir --timeout 1900 -r requirements.txt \
  && apt-get clean autoclean \
  && apt-get autopurge -y \
  && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . .
COPY --from=build-stage /lorawanWrapper.so ./analyzers/rolaguard_bruteforce_analyzer/lorawanwrapper/utils/

ENV PYTHONPATH="/root/app"

ENTRYPOINT ["python3", "LafProcessData.py"]
CMD ["-b"]
