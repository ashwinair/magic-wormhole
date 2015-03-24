from __future__ import print_function
import sys, os, json
from wormhole.blocking.transcribe import Receiver, WrongPasswordError
from wormhole.blocking.transit import TransitReceiver, TransitError
from .progress import start_progress, update_progress, finish_progress

APPID = "lothar.com/wormhole/file-xfer"

def receive_file(args):
    # we're receiving
    transit_receiver = TransitReceiver(transit_relay=args.transit_helper)

    r = Receiver(APPID, args.relay_url)
    code = args.code
    if not code:
        code = r.input_code("Enter receive-file wormhole code: ",
                            args.code_length)
    r.set_code(code)

    mydata = json.dumps({
        "transit": {
            "direct_connection_hints": transit_receiver.get_direct_hints(),
            "relay_connection_hints": transit_receiver.get_relay_hints(),
            },
        }).encode("utf-8")
    try:
        data = json.loads(r.get_data(mydata).decode("utf-8"))
    except WrongPasswordError as e:
        print("ERROR: " + e.explain(), file=sys.stderr)
        return 1
    #print("their data: %r" % (data,))

    file_data = data["file"]
    filename = os.path.basename(file_data["filename"]) # unicode
    filesize = file_data["filesize"]

    # now receive the rest of the owl
    tdata = data["transit"]
    transit_key = r.derive_key(APPID+"/transit-key")
    transit_receiver.set_transit_key(transit_key)
    transit_receiver.add_their_direct_hints(tdata["direct_connection_hints"])
    transit_receiver.add_their_relay_hints(tdata["relay_connection_hints"])
    record_pipe = transit_receiver.connect()

    print("Receiving %d bytes for '%s' (%s).." % (filesize, filename,
                                                  transit_receiver.describe()))

    target = args.output_file
    if not target:
        # allow the sender to specify the filename, but only write to the
        # current directory, and never overwrite anything
        here = os.path.abspath(os.getcwd())
        target = os.path.abspath(os.path.join(here, filename))
        if os.path.dirname(target) != here:
            print("Error: suggested filename (%s) would be outside current directory"
                  % (filename,))
            record_pipe.send_record("bad filename\n")
            record_pipe.close()
            return 1
    if os.path.exists(target):
        print("Error: refusing to overwrite existing file %s" % (filename,))
        record_pipe.send_record("file already exists\n")
        record_pipe.close()
        return 1
    tmp = target + ".tmp"

    with open(tmp, "wb") as f:
        received = 0
        next_update = start_progress(filesize)
        while received < filesize:
            try:
                plaintext = record_pipe.receive_record()
            except TransitError:
                print()
                print("Connection dropped before full file received")
                print("got %d bytes, wanted %d" % (received, filesize))
                return 1
            f.write(plaintext)
            received += len(plaintext)
            next_update = update_progress(next_update, received, filesize)
        finish_progress(filesize)
        assert received == filesize

    os.rename(tmp, target)

    print("Received file written to %s" % target)
    record_pipe.send_record("ok\n")
    record_pipe.close()
    return 0