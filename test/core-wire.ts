// Shared synthetic core protocol fixture. These are test-owned wire values.
export const methods = ['terminal.run', 'terminal.list', 'terminal.get', 'terminal.label', 'terminal.attach', 'terminal.send', 'terminal.wait', 'terminal.read', 'terminal.keys', 'terminal.interrupt', 'terminal.kill', 'events.subscribe', 'doc.get', 'doc.set', 'file.read', 'file.write', 'machine.exec', 'machine.list', 'server.status']
export function frame(channel: number, body: string | Buffer, kind = 0) {
  const bytes = Buffer.from(body)
  const header = Buffer.alloc(9)
  header.writeUInt32LE(channel); header[4] = kind; header.writeUInt32LE(bytes.length, 5)
  return Buffer.concat([header, bytes])
}
