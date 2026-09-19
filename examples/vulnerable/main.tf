##############################################################################
# BlastRadius demo environment
#
# This configuration is intentionally simple and is NEVER applied to a real
# AWS account. It exists only so BlastRadius has realistic Terraform to model.
#
# examples/safe/ and examples/vulnerable/ are identical except for ONE line:
# the SSH ingress CIDR of the web security group (line 28). That single line
# decides whether a path exists from the internet to sensitive data.
##############################################################################

provider "aws" {
  region = "us-east-1"
}

# ---------------------------------------------------------------------------
# Network exposure
# ---------------------------------------------------------------------------
resource "aws_security_group" "web" {
  name        = "web-sg"
  description = "Ingress rules for the public web tier"

  ingress {
    description = "SSH access for operators"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from the internal load balancer subnet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/24"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
resource "aws_instance" "web_server" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  tags = {
    Name = "web-server"
    Role = "public-web-tier"
  }
}

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
resource "aws_iam_role" "app" {
  name = "app-role"

  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
POLICY
}

resource "aws_iam_instance_profile" "app" {
  name = "app-instance-profile"
  role = aws_iam_role.app.name
}

resource "aws_iam_role_policy" "app_s3_read" {
  name = "app-s3-read"
  role = aws_iam_role.app.id

  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "${aws_s3_bucket.customer_data.arn}",
        "${aws_s3_bucket.customer_data.arn}/*"
      ]
    }
  ]
}
POLICY
}

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "customer_data" {
  bucket = "acme-customer-data"

  tags = {
    Name      = "customer-data"
    Sensitive = "true"
    DataClass = "pii"
  }
}
