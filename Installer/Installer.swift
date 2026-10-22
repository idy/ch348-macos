import AppKit
import SystemExtensions

@main
final class Installer: NSObject, NSApplicationDelegate, OSSystemExtensionRequestDelegate {
    private let identifier = "com.idy.ch348-macos.driver"
    private let status = NSTextField(wrappingLabelWithString: "Install the CH348 serial driver to publish eight system serial ports.")
    private var window: NSWindow!

    static func main() {
        let app = NSApplication.shared
        let delegate = Installer()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 230),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "CH348 Serial Driver"
        status.frame = NSRect(x: 25, y: 90, width: 490, height: 115)
        window.contentView?.addSubview(status)
        for (title, action, x) in [("Install / Update", #selector(install), 25), ("Uninstall", #selector(uninstall), 210)] {
            let button = NSButton(title: title, target: self, action: action)
            button.frame = NSRect(x: x, y: 30, width: 170, height: 35)
            window.contentView?.addSubview(button)
        }
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if CommandLine.arguments.contains("--activate") { install() }
    }

    @objc private func install() {
        status.stringValue = "Requesting driver activation…"
        let request = OSSystemExtensionRequest.activationRequest(forExtensionWithIdentifier: identifier, queue: .main)
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }

    @objc private func uninstall() {
        let request = OSSystemExtensionRequest.deactivationRequest(forExtensionWithIdentifier: identifier, queue: .main)
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }

    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        status.stringValue = "Approve CH348 in System Settings → General → Login Items & Extensions → Driver Extensions."
    }

    func request(_ request: OSSystemExtensionRequest, actionForReplacingExtension existing: OSSystemExtensionProperties,
                 withExtension ext: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction { .replace }

    func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) {
        status.stringValue = result == .completed
            ? "Driver registration completed. Connect the CH348 and verify eight IOSerialBSDClient ports."
            : "Registration requires a Mac restart before it takes effect."
        NSLog("CH348 activation result: %ld", result.rawValue)
    }

    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        status.stringValue = "Activation failed: \(error.localizedDescription)\n\((error as NSError).domain) code \((error as NSError).code). Check the DriverKit provisioning profile and signature."
        NSLog("CH348 activation failed: %@", String(describing: error))
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
