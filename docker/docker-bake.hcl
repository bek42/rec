// ==== Baking Variables ====

variable "SOURCE_REPOSITORY_URL" {
  default = null
}

variable "SOURCE_COMMIT" {
  default = null
}

variable "SOURCE_VERSION" {
  default = null
}

variable "BASE_TAGS" {
  default = "testing"
}

variable "CONTAINER_REGISTRIES" {
  default = "rec"
}


// ==== Baking Groups ====

group "default" {
  targets = ["debian"]
}


// ==== Shared Baking ====
function "labels" {
  params = []
  result = {
    "org.opencontainers.image.description" = "Gmail receipt/invoice forwarder - ${SOURCE_VERSION}"
    "org.opencontainers.image.licenses" = "MIT"
    "org.opencontainers.image.url" = "https://github.com/bek42/rec"
    "org.opencontainers.image.created" =  "${formatdate("YYYY-MM-DD'T'hh:mm:ssZZZZZ", timestamp())}"
    "org.opencontainers.image.source" = "${SOURCE_REPOSITORY_URL}"
    "org.opencontainers.image.revision" = "${SOURCE_COMMIT}"
    "org.opencontainers.image.version" = "${SOURCE_VERSION}"
  }
}

target "_default_attributes" {
  labels = labels()
}

// ==== Debian Baking ====

// Default Debian target, will build a container using the hosts platform architecture
// Note: no `ssh = ["default"]` mount here — unlike finapi/fin/nordlink, rec has no
// private git+ssh dependencies (azkees/pylogpy/playwright all resolve from PyPI).
target "debian" {
  inherits = ["_default_attributes"]
  dockerfile = "docker/Dockerfile.debian"
  tags = generate_tags("", platform_tag())
  output = ["type=docker"]
}

// Multi Platform target, will build one tagged manifest with all supported architectures
// This is mainly used by GitHub Actions to build and push new containers
target "debian-multi" {
  inherits = ["debian"]
  platforms = ["linux/amd64", "linux/arm64"]
  tags = generate_tags("", "")
  output = [join(",", flatten([["type=registry"], image_index_annotations()]))]
}

// Per platform targets, to individually test building per platform locally
target "debian-amd64" {
  inherits = ["debian"]
  platforms = ["linux/amd64"]
  tags = generate_tags("", "-amd64")
}

target "debian-arm64" {
  inherits = ["debian"]
  platforms = ["linux/arm64"]
  tags = generate_tags("", "-arm64")
}

// A Group to build all platforms individually for local testing
group "debian-all" {
  targets = ["debian-amd64", "debian-arm64"]
}


// ==== Bake everything locally ====

group "all" {
  targets = ["debian-all"]
}


// ==== Baking functions ====

// This will return the local platform as amd64, arm64 or armv7 for example
// It can be used for creating a local image tag
function "platform_tag" {
  params = []
  result = "-${replace(replace(BAKE_LOCAL_PLATFORM, "linux/", ""), "/", "")}"
}


function "get_container_registries" {
  params = []
  result = flatten(split(",", CONTAINER_REGISTRIES))
}

function "get_base_tags" {
  params = []
  result = flatten(split(",", BASE_TAGS))
}

function "generate_tags" {
  params = [
    suffix,   // What to append to the BASE_TAG when needed, like `-alpine` for example
    platform  // the platform we are building for if needed
  ]
  result = flatten([
    for registry in get_container_registries() :
      [for base_tag in get_base_tags() :
        concat(
          base_tag == "latest" ? suffix == "-alpine" ? ["${registry}:alpine${platform}"] : [] : [],
          ["${registry}:${base_tag}${suffix}${platform}"]
        )
      ]
  ])
}

function "image_index_annotations" {
  params = []
  result = flatten([
    for key, value in labels() :
      value != null ? formatlist("annotation-index.%s=%s", "${key}", "${value}") : []
  ])
}
