resource "aws_security_group" "ssh" {
  name = "blastradius-hosted-test-sg"
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/24"]
  }
}

resource "aws_instance" "app" {
  ami                    = "ami-0c55b159cbfafe1f0"
  instance_type          = "t3.micro"
  vpc_security_group_ids = [aws_security_group.ssh.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  tags = {
    Name = "PR Test Server"
  }
}

resource "aws_iam_role" "app" {
  name = "pr-test-role"
  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
POLICY
}

resource "aws_iam_instance_profile" "app" {
  name = "pr-test-profile"
  role = aws_iam_role.app.name
}

resource "aws_iam_role_policy" "read" {
  role = aws_iam_role.app.id
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "${aws_s3_bucket.data.arn}/*"}]
}
POLICY
}

resource "aws_s3_bucket" "data" {
  bucket = "blastradius-controlled-pr-demo"
  tags = {
    Name      = "PR Test Data"
    Sensitive = "true"
  }
}
