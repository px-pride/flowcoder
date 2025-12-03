"""
FlowCoder - Main Entry Point

A visual flowchart builder for creating custom automated workflows with Claude Code.
"""

import logging
import argparse


def setup_logging(debug: bool = False):
    """Configure logging for the application with security and rotation."""
    from src.utils.logging_config import configure_secure_logging

    level = logging.DEBUG if debug else logging.INFO
    configure_secure_logging(level=level)


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description='FlowCoder - Visual Flowchart Builder')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    setup_logging(args.debug)
    logger = logging.getLogger(__name__)

    logger.info("Starting FlowCoder...")

    # Initialize and launch GUI
    from src.views import MainWindow

    window = MainWindow(title="FlowCoder - Visual Flowchart Builder")
    logger.info("Main window created")

    # Run the application
    window.run()


if __name__ == "__main__":
    main()
