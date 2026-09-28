# Synthetic static-analysis sample. Never apply to AWS.
# The generated candidate changes only the SSH ingress CIDR.

resource "aws_security_group" "web" {
  name = "sample-web"

  ingress {
    description = "Operator SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/24"]
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

resource "aws_instance" "web_server" {
  ami                    = "ami-synthetic-do-not-apply"
  instance_type          = "t3.micro"
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
}

resource "aws_iam_role" "app" {
  name = "sample-app"
  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
POLICY
}

resource "aws_iam_instance_profile" "app" {
  name = "sample-app"
  role = aws_iam_role.app.name
}

resource "aws_iam_role_policy" "app_s3_read" {
  name = "sample-s3-read"
  role = aws_iam_role.app.id
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket"],
    "Resource": [
      "${aws_s3_bucket.customer_data.arn}",
      "${aws_s3_bucket.customer_data.arn}/*"
    ]
  }]
}
POLICY
}

resource "aws_s3_bucket" "customer_data" {
  bucket = "blastradius-synthetic-customer-data"
  tags = {
    Sensitive = "true"
    DataClass = "pii"
  }
}
