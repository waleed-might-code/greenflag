"""
Demo: Large-scale data mining with WARC storage.
Shows how to mine massive amounts of data efficiently.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cyberAI.storage.warc_extractor import WARCExtractor, extract_data_from_engagement
from cyberAI.storage.batch_miner import BatchDataMiner, mine_engagement_at_scale, APIDiscovery


def demo_warc_extraction():
    """Demo: Extract data from existing WARC archives."""
    print("\n" + "="*70)
    print("  DEMO: WARC Data Extraction")
    print("="*70 + "\n")
    
    # Use existing WARC from realistic demo
    engagement_id = "demo_realistic_001"
    warc_dir = Path(f"outputs/warc/{engagement_id}")
    
    if not warc_dir.exists():
        print(f"⚠️  No WARC data found for {engagement_id}")
        print("   Run realistic_demo.py first to generate WARC files")
        return
    
    print(f"📦 Extracting data from: {warc_dir}\n")
    
    extractor = WARCExtractor(warc_dir)
    
    # Get statistics
    print("📊 WARC Statistics:")
    stats = extractor.get_statistics()
    print(f"   Files: {stats['total_files']}")
    print(f"   Total records: {stats['total_records']}")
    print(f"   Requests: {stats['requests']}")
    print(f"   Responses: {stats['responses']}")
    print(f"   Unique URLs: {stats['unique_urls']}")
    
    print(f"\n   HTTP Methods:")
    for method, count in stats['methods'].items():
        print(f"     {method}: {count}")
    
    print(f"\n   Content Types:")
    for ct, count in stats['content_types'].items():
        print(f"     {ct}: {count}")
    
    # Discover endpoints
    print(f"\n🔍 Discovered Endpoints:")
    endpoints = extractor.discover_endpoints()
    for endpoint_key, metadata in list(endpoints.items())[:10]:
        print(f"   {endpoint_key}")
        print(f"     Count: {metadata['count']}")
        print(f"     First seen: {metadata['first_seen']}")
    
    if len(endpoints) > 10:
        print(f"   ... and {len(endpoints) - 10} more")
    
    # Extract JSON data
    print(f"\n📄 Extracting JSON Data:")
    json_data = list(extractor.extract_json_data())
    print(f"   Found {len(json_data)} JSON responses")
    
    if json_data:
        print(f"\n   Sample JSON response:")
        sample = json_data[0]
        print(f"     URL: {sample['url']}")
        print(f"     Date: {sample['date']}")
        print(f"     Data: {str(sample['data'])[:100]}...")
    
    # Extract parameters
    print(f"\n🔑 Discovered Parameters:")
    params = extractor.extract_parameters()
    for param_name, values in list(params.items())[:5]:
        print(f"   {param_name}: {len(values)} unique values")
        if values:
            print(f"     Examples: {list(values)[:3]}")
    
    print(f"\n✅ Extraction complete!")
    print(f"   Total data points extracted: {stats['total_records']}")


async def demo_batch_mining():
    """Demo: Batch mining at scale."""
    print("\n" + "="*70)
    print("  DEMO: Batch Data Mining")
    print("="*70 + "\n")
    
    engagement_id = "demo_batch_001"
    
    print(f"🚀 Starting batch mining for engagement: {engagement_id}\n")
    
    # Create miner
    miner = BatchDataMiner(
        engagement_id=engagement_id,
        max_workers=5,
        rate_limit_rps=10
    )
    
    # Add targets (simulating discovered endpoints)
    print("📋 Adding targets...")
    targets = [
        "https://api.target.com/users",
        "https://api.target.com/users/1",
        "https://api.target.com/users/2",
        "https://api.target.com/products",
        "https://api.target.com/products/123",
        "https://api.target.com/orders",
        "https://api.target.com/admin/settings",
        "https://api.target.com/admin/users",
        "https://api.target.com/api/v1/search",
        "https://api.target.com/api/v1/analytics",
    ]
    
    for url in targets:
        miner.add_target(url)
    
    print(f"   Added {len(targets)} targets\n")
    
    # Progress callback
    def progress(completed, total):
        pct = completed / total * 100
        print(f"\r   Progress: {completed}/{total} ({pct:.1f}%)", end="", flush=True)
    
    # Mine all
    print("⛏️  Mining data...")
    await miner.mine_all(progress_callback=progress)
    print()  # New line
    
    # Get statistics
    stats = miner.get_statistics()
    print(f"\n📊 Mining Statistics:")
    print(f"   Total targets: {stats['total_targets']}")
    print(f"   Completed: {stats['completed']}")
    print(f"   Failed: {stats['failed']}")
    print(f"   Success rate: {stats['success_rate']*100:.1f}%")
    
    print(f"\n💾 Data stored in: outputs/warc/{engagement_id}/")
    print(f"✅ Batch mining complete!")


def demo_api_discovery():
    """Demo: API endpoint discovery."""
    print("\n" + "="*70)
    print("  DEMO: API Discovery")
    print("="*70 + "\n")
    
    print("🔍 Discovering API endpoints from JavaScript...\n")
    
    # Sample JavaScript code
    js_code = """
    const API_BASE = "https://api.target.com";
    
    fetch("/api/users")
        .then(res => res.json());
    
    axios.get("https://api.target.com/products");
    axios.post("/api/orders", data);
    
    const endpoints = {
        users: "/api/v1/users",
        products: "/api/v1/products",
        search: "https://api.target.com/search"
    };
    """
    
    # Discover endpoints
    urls = APIDiscovery.from_javascript(js_code)
    
    print(f"📍 Discovered {len(urls)} endpoints:")
    for url in urls:
        print(f"   {url}")
    
    print(f"\n✅ API discovery complete!")


if __name__ == "__main__":
    import asyncio
    
    print("\n" + "╔" + "="*68 + "╗")
    print("║" + " "*68 + "║")
    print("║" + "  🎯 LARGE-SCALE DATA MINING DEMO 🎯".center(68) + "║")
    print("║" + " "*68 + "║")
    print("╚" + "="*68 + "╝")
    
    # Run demos
    demo_warc_extraction()
    asyncio.run(demo_batch_mining())
    demo_api_discovery()
    
    print("\n" + "="*70)
    print("  ALL DEMOS COMPLETE")
    print("="*70)
    print("\n💡 Key Capabilities Demonstrated:")
    print("   ✓ Extract data from WARC archives")
    print("   ✓ Batch mining with rate limiting")
    print("   ✓ API endpoint discovery")
    print("   ✓ Concurrent data collection")
    print("   ✓ Evidence-backed data mining")
    print("\n🚀 Ready for large-scale data collection!\n")
