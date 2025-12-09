using System;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace DAFC_GUI
{
    public class UnixEndPoint : EndPoint
    {
        private const int MaxPathLength = 106;
        private string _filename;

        public UnixEndPoint(string filename)
        {
            if (filename == null)
                throw new ArgumentNullException(nameof(filename));

            byte[] bytes = Encoding.UTF8.GetBytes(filename);
            if (bytes.Length > MaxPathLength)
                throw new ArgumentException($"Socket path too long. Maximum is {MaxPathLength} bytes, got {bytes.Length} bytes.", nameof(filename));

            _filename = filename;
        }

        public string Filename
        {
            get { return _filename; }
            set { _filename = value; }
        }

        public override AddressFamily AddressFamily
        {
            get { return AddressFamily.Unix; }
        }

        public override EndPoint Create(SocketAddress socketAddress)
        {
            return new UnixEndPoint(_filename);
        }

        public override SocketAddress Serialize()
        {
            // Unix domain sockets path max length is 108 bytes
            byte[] bytes = Encoding.UTF8.GetBytes(_filename);
            SocketAddress socketAddress = new SocketAddress(AddressFamily.Unix, 108);
            
            for (int i = 0; i < bytes.Length; i++)
            {
                socketAddress[2 + i] = bytes[i];
            }

            return socketAddress;
        }

        public override string ToString()
        {
            return _filename;
        }
    }
}
