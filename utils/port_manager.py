#!/usr/bin/env python3
"""
Port management utility for FloodMap.
Helps find available ports and manage conflicts.
"""

import os
import socket
import subprocess


class PortManager:
    """Manages port allocation and conflict resolution."""

    def __init__(self):
        self.default_ports = {
            "API_PORT": 5002,
            "TILESERVER_PORT": 8080,
            "FRONTEND_PORT": 3000,
        }

    def is_port_available(self, port: int) -> bool:
        """Check if a port is available."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", port))
                return result != 0
        except Exception:
            return False

    def find_available_port(
        self, start_port: int, max_attempts: int = 50
    ) -> int | None:
        """Find the next available port starting from start_port."""
        for port in range(start_port, start_port + max_attempts):
            if self.is_port_available(port):
                return port
        return None

    def get_port_usage(self) -> dict[int, str]:
        """Get what processes are using common ports."""
        usage = {}

        try:
            # Use lsof to find port usage
            result = subprocess.run(
                ["lsof", "-i", "-P", "-n"], capture_output=True, text=True
            )

            for line in result.stdout.split("\n"):
                if ":" in line and ("LISTEN" in line or "ESTABLISHED" in line):
                    parts = line.split()
                    if len(parts) > 8:
                        port_info = parts[8]
                        if ":" in port_info:
                            try:
                                port = int(port_info.split(":")[-1])
                                process = parts[0]
                                usage[port] = process
                            except ValueError:
                                pass
        except Exception:
            pass

        return usage

    def suggest_ports(self) -> dict[str, int]:
        """Suggest available ports for FloodMap services."""
        suggestions = {}
        port_usage = self.get_port_usage()

        for service, default_port in self.default_ports.items():
            if self.is_port_available(default_port):
                suggestions[service] = default_port
            else:
                # Find alternative
                alt_port = self.find_available_port(default_port + 1)
                if alt_port:
                    suggestions[service] = alt_port
                    print(
                        f"⚠️  {service} default port {default_port} busy (used by {port_usage.get(default_port, 'unknown')})"
                    )
                    print(f"💡 Suggesting {service}={alt_port}")
                else:
                    print(f"❌ Could not find available port for {service}")

        return suggestions

    def create_env_file(self, ports: dict[str, int], env_path: str = ".env"):
        """Create .env file with suggested ports."""
        with open(env_path, "w") as f:
            f.write("# FloodMap Port Configuration\n")
            f.write("# Generated automatically to avoid conflicts\n\n")

            for service, port in ports.items():
                f.write(f"{service}={port}\n")

            f.write("\n# TileServer URL (used by API)\n")
            f.write(
                f"TILESERVER_URL=http://localhost:{ports.get('TILESERVER_PORT', 8080)}\n"
            )

        print(f"✅ Created {env_path} with available ports")

    def show_port_status(self):
        """Show current port status for FloodMap services."""
        print("🔍 FloodMap Port Status:")
        print("-" * 40)

        port_usage = self.get_port_usage()

        for service, default_port in self.default_ports.items():
            env_port = int(os.getenv(service.replace("_PORT", "_PORT"), default_port))

            if self.is_port_available(env_port):
                status = "✅ Available"
            else:
                process = port_usage.get(env_port, "Unknown process")
                status = f"❌ In use by {process}"

            print(f"{service:15} {env_port:5d} - {status}")


def main():
    """Main CLI interface."""
    import sys

    manager = PortManager()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "status":
            manager.show_port_status()
        elif command == "suggest":
            suggestions = manager.suggest_ports()
            print("\n💡 Suggested port configuration:")
            for service, port in suggestions.items():
                print(f"export {service}={port}")
        elif command == "fix":
            suggestions = manager.suggest_ports()
            manager.create_env_file(suggestions)
        else:
            print("Usage: python port_manager.py [status|suggest|fix]")
    else:
        print("🔧 FloodMap Port Manager")
        print("\nCommands:")
        print("  status  - Show current port usage")
        print("  suggest - Suggest available ports")
        print("  fix     - Create .env file with available ports")


if __name__ == "__main__":
    main()
