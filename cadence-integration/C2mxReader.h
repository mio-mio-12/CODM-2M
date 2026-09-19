#pragma once
// Standalone C++17 footer/directory reader. Chunk bodies are UTF-8 JSON.
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace codm {
inline std::uint64_t little(const unsigned char* p, unsigned n) {
    std::uint64_t v=0; for(unsigned i=0;i<n;++i)v|=std::uint64_t(p[i])<<(8*i); return v;
}
struct C2mxChunks { bool present=false; std::map<std::string,std::string> json; };
inline C2mxChunks readC2mx(const std::filesystem::path& path) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f)throw std::runtime_error("Cannot open map");
    const auto end=f.tellg(); if(end<32)return {};
    const auto size=static_cast<std::uint64_t>(end);
    std::array<unsigned char,32> footer{};f.seekg(end-std::streamoff(32));
    if(!f.read(reinterpret_cast<char*>(footer.data()),32))throw std::runtime_error("Short footer");
    if(std::string(reinterpret_cast<char*>(footer.data()),4)!="C2MX")return {};
    const auto version=little(footer.data()+4,4),offset=little(footer.data()+8,8),length=little(footer.data()+16,8);
    const auto count=little(footer.data()+24,4),flags=little(footer.data()+28,4);
    if(version!=1||flags||count>4096||length!=count*24||offset>size-32||length!=size-32-offset)
        throw std::runtime_error("Invalid C2MX directory");
    struct Entry { std::string tag; std::uint64_t version,start,length; };
    std::vector<Entry> entries; f.seekg(static_cast<std::streamoff>(offset));
    for(std::uint64_t i=0;i<count;++i){
        std::array<unsigned char,24> b{};
        if(!f.read(reinterpret_cast<char*>(b.data()),24))throw std::runtime_error("Short C2MX directory");
        entries.push_back({std::string(reinterpret_cast<char*>(b.data()),4),little(b.data()+4,4),little(b.data()+8,8),little(b.data()+16,8)});
    }
    C2mxChunks result;result.present=true;std::vector<std::pair<std::uint64_t,std::uint64_t>> spans;
    for(const auto& e:entries){
        if(e.start<5||e.start>offset||e.length>offset-e.start||e.length>512ull*1024*1024)
            throw std::runtime_error("Invalid C2MX chunk bounds");
        for(const auto& span:spans)if(e.start<span.second&&e.start+e.length>span.first)
            throw std::runtime_error("Overlapping C2MX chunks");
        spans.emplace_back(e.start,e.start+e.length);
        if(e.version!=1)throw std::runtime_error("Unsupported C2MX chunk version");
        if(result.json.count(e.tag))throw std::runtime_error("Duplicate C2MX chunk");
        std::string body(static_cast<std::size_t>(e.length),'\0');f.seekg(static_cast<std::streamoff>(e.start));
        if(!f.read(body.data(),static_cast<std::streamsize>(body.size())))throw std::runtime_error("Short C2MX chunk");
        result.json.emplace(e.tag,std::move(body));
    }
    return result;
}
} // namespace codm
